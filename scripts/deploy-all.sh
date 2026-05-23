#!/usr/bin/env bash
#
# Deploy the NNDSS Health Agent from scratch.
#
# Deploys: MinIO → Trino → Agent → Pipeline Server → RBAC → Secrets
# Prereqs: oc, helm, mc, python3 with trino/pandas/openpyxl
#
# Usage:
#   export MAAS_API_KEY=<jwt_token>
#   ./scripts/deploy-all.sh
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

NAMESPACE="${NAMESPACE:-nndss-agent}"
MINIO_NAMESPACE="${MINIO_NAMESPACE:-minio}"
MAAS_API_KEY="${MAAS_API_KEY:-}"
MAAS_BASE_URL="${MAAS_BASE_URL:-http://maas.apps.ocp.cloud.rhai-tmm.dev/prelude-maas}"

echo "============================================"
echo "  NNDSS Health Agent — Full Deployment"
echo "============================================"
echo "Namespace: ${NAMESPACE}"
echo "MinIO namespace: ${MINIO_NAMESPACE}"
echo ""

# ── 1. Create namespace ───────────────────────────────────────
echo "==> 1. Creating namespace: ${NAMESPACE}"
oc new-project "${NAMESPACE}" 2>/dev/null || oc project "${NAMESPACE}"

# ── 2. Deploy MinIO ───────────────────────────────────────────
echo "==> 2. Deploying MinIO"
oc apply -k "${REPO_DIR}/deploy/minio/overlays/cluster-dev"
echo "Waiting for MinIO..."
oc rollout status deployment/minio -n "${MINIO_NAMESPACE}" --timeout=120s

# Create API route if not exists
oc get route minio-api -n "${MINIO_NAMESPACE}" 2>/dev/null || \
  oc create route edge minio-api --service=minio --port=9000 -n "${MINIO_NAMESPACE}"

MINIO_API=$(oc get route minio-api -n "${MINIO_NAMESPACE}" -o jsonpath='{.spec.host}')
mc alias set nndss "https://${MINIO_API}" minio minio1234

# ── 3. Create MinIO buckets ───────────────────────────────────
echo "==> 3. Creating MinIO buckets"
mc mb --ignore-existing nndss/nndss-data
mc mb --ignore-existing nndss/pipeline-artifacts

# ── 4. Upload NNDSS data ──────────────────────────────────────
echo "==> 4. Uploading NNDSS data"
S3_ENDPOINT="https://${MINIO_API}" S3_ACCESS_KEY=minio S3_SECRET_KEY=minio1234 \
  "${REPO_DIR}/scripts/upload-data.sh"

# ── 5. Deploy Trino ───────────────────────────────────────────
echo "==> 5. Deploying Trino"
if [ -z "${MAAS_API_KEY}" ]; then
  echo "ERROR: Set MAAS_API_KEY environment variable"
  exit 1
fi

cd "${REPO_DIR}/deploy/trino-chart"
SKIP_MINIO=true SKIP_DATA=true SKIP_UI=true \
  MINIO_NAMESPACE="${MINIO_NAMESPACE}" \
  TRINO_NAMESPACE="${NAMESPACE}" \
  OPENAI_API_KEY="${MAAS_API_KEY}" \
  OPENAI_BASE_URL="${MAAS_BASE_URL}/qwen36-27b" \
  OPENAI_MODEL="qwen36-27b" \
  S3_BUCKET="nndss-data" \
  ./install.sh
cd "${REPO_DIR}"

# ── 6. Load data into Trino ──────────────────────────────────
echo "==> 6. Loading data into Trino"
oc port-forward svc/trino -n "${NAMESPACE}" 8090:8080 &
PF_PID=$!
sleep 5

TRINO_HOST=localhost TRINO_PORT=8090 \
  DATA_DIR="${REPO_DIR}/agents/nndss-mcp-server/data" \
  python3 "${REPO_DIR}/scripts/load-nndss-trino.py"

TRINO_HOST=localhost TRINO_PORT=8090 \
  python3 "${REPO_DIR}/scripts/load-population-trino.py"

kill $PF_PID 2>/dev/null || true

# ── 7. Create secrets ─────────────────────────────────────────
echo "==> 7. Creating secrets"
oc create secret generic nndss-agent-maas-key \
  --from-literal=api-key="${MAAS_API_KEY}" \
  -n "${NAMESPACE}" 2>/dev/null || echo "Secret already exists"

oc apply -f "${REPO_DIR}/deploy/pipeline-s3-secret.yaml" -n "${NAMESPACE}"

# ── 8. Deploy RBAC ────────────────────────────────────────────
echo "==> 8. Deploying RBAC"
oc apply -f "${REPO_DIR}/deploy/mlflow-rbac.yaml" -n "${NAMESPACE}"
oc apply -f "${REPO_DIR}/deploy/pipeline-mlflow-rbac.yaml" -n "${NAMESPACE}"

# ── 9. Deploy agent ───────────────────────────────────────────
echo "==> 9. Deploying agent"
oc apply -k "${REPO_DIR}/agents/nndss-agent/deploy" -n "${NAMESPACE}"
oc rollout status deployment/nndss-agent -n "${NAMESPACE}" --timeout=120s

# ── 10. Deploy pipeline server (DSPA) ─────────────────────────
echo "==> 10. Deploying pipeline server"
oc apply -f "${REPO_DIR}/deploy/dspa.yaml" -n "${NAMESPACE}"
echo "Waiting for DSPA..."
sleep 30
oc rollout status deployment/ds-pipeline-dspa -n "${NAMESPACE}" --timeout=120s

# ── 11. Compile and submit eval pipeline ─────────────────────
echo "==> 11. Compiling and submitting eval pipeline"
python3 "${REPO_DIR}/evaluations/pipeline.py" --compile

DSPA_ROUTE=$(oc get route -n "${NAMESPACE}" -l app=ds-pipeline-dspa -o jsonpath='{.items[0].spec.host}' 2>/dev/null)
if [ -n "${DSPA_ROUTE}" ]; then
  SA_TOKEN=$(oc whoami -t)
  PIPELINE_FILE="${REPO_DIR}/evaluations/pipelines_gen/nndss-eval-pipeline.yaml"

  # Upload pipeline (ignore error if name already exists)
  PIPELINE_ID=$(curl -ks -X POST "https://${DSPA_ROUTE}/apis/v2beta1/pipelines/upload" \
    -H "Authorization: Bearer ${SA_TOKEN}" \
    -F "uploadfile=@${PIPELINE_FILE}" \
    -F "name=nndss-health-eval" 2>/dev/null \
    | python3 -c "import sys,json; print(json.load(sys.stdin).get('pipeline_id',''))" 2>/dev/null)

  if [ -z "${PIPELINE_ID}" ]; then
    # Pipeline exists — find its ID
    PIPELINE_ID=$(curl -ks "https://${DSPA_ROUTE}/apis/v2beta1/pipelines?page_size=50" \
      -H "Authorization: Bearer ${SA_TOKEN}" \
      | python3 -c "import sys,json; d=json.load(sys.stdin); print(next((p['pipeline_id'] for p in d.get('pipelines',[]) if p['display_name']=='nndss-health-eval'),''))" 2>/dev/null)

    if [ -n "${PIPELINE_ID}" ]; then
      # Upload new version via kfp client
      python3 -c "
import kfp, warnings
warnings.filterwarnings('ignore')
client = kfp.Client(host='https://${DSPA_ROUTE}', existing_token='${SA_TOKEN}', ssl_ca_cert=None)
client._is_ipython = False
result = client.upload_pipeline_version(
    pipeline_package_path='${PIPELINE_FILE}',
    pipeline_version_name='$(date +%Y%m%d-%H%M%S)',
    pipeline_id='${PIPELINE_ID}',
)
print(f'Pipeline version: {result.pipeline_version_id}')
" 2>/dev/null
    fi
  fi
  echo "Eval pipeline uploaded to DSPA"
else
  echo "WARNING: No DSPA route found. Upload eval pipeline manually."
fi

# ── 12. Routes ────────────────────────────────────────────────
echo ""
echo "============================================"
echo "  Deployment Complete"
echo "============================================"
echo ""
echo "Routes:"
oc get routes -n "${NAMESPACE}" -o custom-columns='NAME:.metadata.name,HOST:.spec.host' --no-headers
echo ""
echo "Pods:"
oc get pods -n "${NAMESPACE}" --no-headers | awk '{print "  " $1, $2, $3}'
echo ""
echo "Next: Run eval pipeline from RHOAI Data Science Pipelines UI"
echo "  or: make eval-submit"

#!/usr/bin/env bash
# Compile and submit an eval pipeline run.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

NAMESPACE="${NAMESPACE:-nndss-agent}"
PIPELINE_FILE="${REPO_DIR}/evaluations/pipelines_gen/nndss-eval-pipeline.yaml"

echo "==> Compiling pipeline..."
python3 "${REPO_DIR}/evaluations/pipeline.py" --compile

DSPA_ROUTE=$(oc get route -n "${NAMESPACE}" -l app=ds-pipeline-dspa -o jsonpath='{.items[0].spec.host}')
SA_TOKEN=$(oc whoami -t)

# Find pipeline ID
PIPELINE_ID=$(curl -ks "https://${DSPA_ROUTE}/apis/v2beta1/pipelines?page_size=50" \
  -H "Authorization: Bearer ${SA_TOKEN}" \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(next((p['pipeline_id'] for p in d.get('pipelines',[]) if 'nndss' in p['display_name'].lower()),''))")

if [ -z "${PIPELINE_ID}" ]; then
  echo "No eval pipeline found. Upload one first via deploy-all.sh"
  exit 1
fi

# Upload new version
echo "==> Uploading pipeline version..."
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
print(f'Version: {result.pipeline_version_id}')
version_id = result.pipeline_version_id

# Submit run
import json
run = client.create_run_from_pipeline_package(
    pipeline_file='${PIPELINE_FILE}',
    run_name='eval-$(date +%Y%m%d-%H%M%S)',
    arguments={
        'mlflow_tracking_uri': 'https://mlflow.redhat-ods-applications.svc:8443/mlflow',
        'mlflow_workspace': '${NAMESPACE}',
        'mlflow_experiment_name': 'nndss-data-agent',
        'dataset_name': 'nndss_health_eval',
        'llm_base_url': 'http://maas.apps.ocp.cloud.rhai-tmm.dev/prelude-maas/gemma4/v1',
        'agent_model': 'kimi-k2-6',
        'judge_model': 'gemma4',
        'trino_host': 'trino.${NAMESPACE}.svc.cluster.local',
        'trino_port': 8080,
        'llm_secret_name': 'nndss-agent-maas-key',
    },
)
print(f'Run submitted: {run.run_id[:12]}...')
"

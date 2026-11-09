#!/usr/bin/env bash
# Switch the agent model in deployment.yaml and eval-submit.sh.
# MaaS body-based routing: MODEL_ENDPOINT is the shared /v1 root and the
# model is the FULL publisher path (publishers/<ns>/models/<name>), sent
# in the request body's "model" field.
# Usage: ./scripts/set-model.sh <full-publisher-path>
#   e.g. ./scripts/set-model.sh publishers/prelude-maas/models/glm-53-flash
set -euo pipefail

MODEL="${1:?Usage: $0 <full-publisher-path>  e.g. publishers/prelude-maas/models/glm-53-flash}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
MAAS_BASE_URL="${MAAS_BASE_URL:-https://maas.apps.ocp.cloud.rhai-tmm.dev/v1}"

DEPLOY="${REPO_DIR}/agents/nndss-agent/deploy/deployment.yaml"
EVAL="${REPO_DIR}/scripts/eval-submit.sh"

# deployment.yaml: update MODEL_NAME and MODEL_ENDPOINT env vars
python3 -c "
import re, sys

content = open('${DEPLOY}').read()

# Replace MODEL_NAME value
content = re.sub(
    r'(- name: MODEL_NAME\n\s+value: )\"[^\"]+\"',
    r'\1\"${MODEL}\"',
    content)

# Replace MODEL_ENDPOINT value — shared /v1 root, no model suffix
content = re.sub(
    r'(- name: MODEL_ENDPOINT\n\s+value: )\"[^\"]+\"',
    r'\1\"${MAAS_BASE_URL}\"',
    content)

open('${DEPLOY}', 'w').write(content)
"

# eval-submit.sh: update agent_model parameter
sed -i "s|'agent_model': '.*'|'agent_model': '${MODEL}'|" "${EVAL}"

echo "Model switched to: ${MODEL}"
echo ""
grep -A1 "MODEL_NAME\|MODEL_ENDPOINT" "${DEPLOY}" | head -4
echo ""
grep "agent_model" "${EVAL}"

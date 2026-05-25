#!/usr/bin/env bash
# Switch the agent model in deployment.yaml and eval-submit.sh.
# Usage: ./scripts/set-model.sh <model-name>
set -euo pipefail

MODEL="${1:?Usage: $0 <model-name>  e.g. kimi-k2-6}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
MAAS_BASE_URL="${MAAS_BASE_URL:-http://maas.apps.ocp.cloud.rhai-tmm.dev/prelude-maas}"

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

# Replace MODEL_ENDPOINT value
content = re.sub(
    r'(- name: MODEL_ENDPOINT\n\s+value: )\"[^\"]+\"',
    r'\1\"${MAAS_BASE_URL}/${MODEL}/v1\"',
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

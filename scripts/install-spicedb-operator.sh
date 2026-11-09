#!/usr/bin/env bash
# Install the SpiceDB operator — CLUSTER-SCOPED (default) or NAMESPACED.
#
# Scope is chosen by the 2nd argument or the SPICEDB_OPERATOR_SCOPE env var
# (cluster | namespaced, default: cluster).
#
#   cluster    normal default — operator in the dedicated "spicedb-operator"
#              namespace, watches ALL namespaces (ClusterRole/ClusterRoleBinding)
#   namespaced for widely-shared clusters — operator runs INSIDE <namespace>
#              and watches ONLY <namespace> (Role/RoleBinding). One operator
#              per namespace; SpiceDBCluster instances stay per-namespace.
#
# The CRD (deploy/spicedb/crd.yaml) is unavoidably cluster-scoped and is
# installed once per cluster in both modes.
#
# Usage:
#   ./scripts/install-spicedb-operator.sh <namespace> [cluster|namespaced]
#   SPICEDB_OPERATOR_SCOPE=namespaced ./scripts/install-spicedb-operator.sh user-mhepburn
#
# Idempotent: safe to run on every deploy (deploy-all.sh calls it). If an
# operator already exists in either location it is left alone (with a notice)
# rather than installing a second reconciler that would fight over the CRs.
set -euo pipefail

NAMESPACE="${1:?Usage: $0 <namespace> [cluster|namespaced]}"
SCOPE="${2:-${SPICEDB_OPERATOR_SCOPE:-cluster}}"
case "${SCOPE}" in
  cluster|namespaced) ;;
  *) echo "ERROR: scope must be 'cluster' or 'namespaced' (got: ${SCOPE})" >&2; exit 1 ;;
esac

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
OP_DIR="${REPO_DIR}/deploy/spicedb"

# ── CRD — cluster-scoped, install once per cluster (both modes) ──
if ! oc get crd spicedbclusters.authzed.com >/dev/null 2>&1; then
  echo "==> Installing SpiceDBCluster CRD (cluster-scoped)"
  oc apply --server-side -f "${OP_DIR}/crd.yaml"
else
  echo "==> SpiceDBCluster CRD already present"
fi

# ── Detect an existing operator in either location ──────────────
if oc get deployment spicedb-operator -n "${NAMESPACE}" >/dev/null 2>&1; then
  echo "==> SpiceDB operator already installed (namespaced) in ${NAMESPACE} — leaving as is"
  exit 0
fi
if oc get deployment spicedb-operator -n spicedb-operator >/dev/null 2>&1; then
  echo "==> SpiceDB operator already installed (cluster-scoped) in spicedb-operator ns — leaving as is"
  echo "    (requested scope: ${SCOPE}; remove the existing operator first to switch)"
  exit 0
fi

# ── Install for the requested scope ─────────────────────────────
if [ "${SCOPE}" = "namespaced" ]; then
  echo "==> Installing SpiceDB operator (namespaced) in ${NAMESPACE}, watching only ${NAMESPACE}"
  sed "s/__NAMESPACE__/${NAMESPACE}/g" "${OP_DIR}/operator-namespaced.yaml" \
    | oc apply -n "${NAMESPACE}" -f -
  oc rollout status deployment/spicedb-operator -n "${NAMESPACE}" --timeout=120s
else
  echo "==> Installing SpiceDB operator (cluster-scoped) in spicedb-operator namespace"
  oc apply -f "${OP_DIR}/operator-cluster.yaml"
  oc rollout status deployment/spicedb-operator -n spicedb-operator --timeout=120s
fi

echo "==> SpiceDB operator ready (scope: ${SCOPE})"

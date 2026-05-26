#!/usr/bin/env bash
set -euo pipefail

SPICEDB_NS="${SPICEDB_NS:-spicedb}"
SPICEDB_SVC="dev"
SPICEDB_PORT=50051
LOCAL_PORT=50051
SCHEMA_FILE="agents/nndss-agent/spicedb/schema.zed"
SEED_SCRIPT="agents/nndss-agent/spicedb/seed_relationships.py"
TOKEN="${SPICEDB_TOKEN:-averysecretpresharedkey}"

usage() {
    cat <<EOF
Usage: $0 <command> [args]

Commands:
  schema                          Write schema from schema.zed to SpiceDB
  seed                            Seed test users, datasets, and relationships
  check <user> <perm> <dataset>   Check a permission (e.g. check admin query notifications)
  grant <user> <relation> <dataset>   Add a relationship
  revoke <user> <relation> <dataset>  Remove a relationship
EOF
    exit 1
}

start_port_forward() {
    oc port-forward -n "$SPICEDB_NS" "svc/$SPICEDB_SVC" "$LOCAL_PORT:$SPICEDB_PORT" &>/dev/null &
    PF_PID=$!
    trap "kill $PF_PID 2>/dev/null || true" EXIT
    sleep 2
}

require_zed() {
    if ! command -v zed &>/dev/null; then
        echo "Error: 'zed' CLI not found. Install from https://github.com/authzed/zed"
        exit 1
    fi
}

cmd_schema() {
    require_zed
    start_port_forward
    echo "Writing schema from $SCHEMA_FILE..."
    zed schema write --endpoint "localhost:$LOCAL_PORT" --token "$TOKEN" --insecure "$SCHEMA_FILE"
    echo "Schema written."
}

cmd_seed() {
    start_port_forward
    echo "Seeding relationships..."
    SPICEDB_ENDPOINT="localhost:$LOCAL_PORT" SPICEDB_TOKEN="$TOKEN" \
        python3 "$SEED_SCRIPT"
    echo "Seeding complete."
}

cmd_check() {
    local user="${1:?Usage: check <user> <perm> <dataset>}"
    local perm="${2:?Usage: check <user> <perm> <dataset>}"
    local dataset="${3:?Usage: check <user> <perm> <dataset>}"

    require_zed
    start_port_forward
    echo "Checking: can user:$user $perm dataset:$dataset?"
    zed permission check --endpoint "localhost:$LOCAL_PORT" --token "$TOKEN" --insecure \
        "dataset:$dataset" "$perm" "user:$user"
}

cmd_grant() {
    local user="${1:?Usage: grant <user> <relation> <dataset>}"
    local relation="${2:?Usage: grant <user> <relation> <dataset>}"
    local dataset="${3:?Usage: grant <user> <relation> <dataset>}"

    require_zed
    start_port_forward
    echo "Granting: user:$user is $relation on dataset:$dataset"
    zed relationship create --endpoint "localhost:$LOCAL_PORT" --token "$TOKEN" --insecure \
        "dataset:$dataset" "$relation" "user:$user"
    echo "Granted."
}

cmd_revoke() {
    local user="${1:?Usage: revoke <user> <relation> <dataset>}"
    local relation="${2:?Usage: revoke <user> <relation> <dataset>}"
    local dataset="${3:?Usage: revoke <user> <relation> <dataset>}"

    require_zed
    start_port_forward
    echo "Revoking: user:$user $relation on dataset:$dataset"
    zed relationship delete --endpoint "localhost:$LOCAL_PORT" --token "$TOKEN" --insecure \
        "dataset:$dataset" "$relation" "user:$user"
    echo "Revoked."
}

[[ $# -lt 1 ]] && usage

case "$1" in
    schema)  cmd_schema ;;
    seed)    cmd_seed ;;
    check)   shift; cmd_check "$@" ;;
    grant)   shift; cmd_grant "$@" ;;
    revoke)  shift; cmd_revoke "$@" ;;
    *)       usage ;;
esac

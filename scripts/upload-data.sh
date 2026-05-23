#!/usr/bin/env bash
#
# Upload NNDSS Excel datasets to MinIO S3 bucket.
#
# Usage:
#   ./scripts/upload-data.sh                          # uses defaults
#   S3_ENDPOINT=https://minio.example.com ./scripts/upload-data.sh
#
# Prerequisites:
#   - mc (MinIO client) installed: https://min.io/docs/minio/linux/reference/minio-mc.html
#   - Data files in agents/nndss-mcp-server/data/
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
DATA_DIR="${REPO_DIR}/agents/nndss-mcp-server/data"

S3_ENDPOINT="${S3_ENDPOINT:-http://minio:9000}"
S3_ACCESS_KEY="${S3_ACCESS_KEY:-minio}"
S3_SECRET_KEY="${S3_SECRET_KEY:-minio1234}"
S3_BUCKET="${S3_BUCKET:-nndss-data}"
MC_ALIAS="nndss"

echo "==> Configuring mc alias: ${MC_ALIAS} -> ${S3_ENDPOINT}"
mc alias set "${MC_ALIAS}" "${S3_ENDPOINT}" "${S3_ACCESS_KEY}" "${S3_SECRET_KEY}"

echo "==> Creating bucket: ${S3_BUCKET}"
mc mb --ignore-existing "${MC_ALIAS}/${S3_BUCKET}"

echo "==> Uploading NNDSS datasets from ${DATA_DIR}"
for f in influenza.xlsx meningococcal.xlsx pneumococcal.xlsx salmonellosis.xlsx; do
    fpath="${DATA_DIR}/${f}"
    if [ -f "${fpath}" ]; then
        echo "    ${f} ($(du -h "${fpath}" | cut -f1))"
        mc cp "${fpath}" "${MC_ALIAS}/${S3_BUCKET}/${f}"
    else
        echo "    SKIP: ${f} not found"
    fi
done

echo "==> Listing bucket contents:"
mc ls "${MC_ALIAS}/${S3_BUCKET}/"

echo "==> Done"

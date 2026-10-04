#!/usr/bin/env bash
# Run on the server from the repository root, after `docker compose up -d qdrant`:
#   bash deploy/restore-knowledge-base.sh ~/fjara_knowledge_v1-....snapshot
# Uploads a snapshot exported by export-knowledge-base.ps1 and restores the
# collection (creating it if needed). No embeddings are recomputed.
set -euo pipefail
SNAPSHOT="${1:?Usage: bash deploy/restore-knowledge-base.sh path/to/file.snapshot}"
COLLECTION="${QDRANT_COLLECTION:-fjara_knowledge_v1}"
QDRANT="${QDRANT_HOST_URL:-http://127.0.0.1:16333}"
[ -f "$SNAPSHOT" ] || { echo "Snapshot not found: $SNAPSHOT" >&2; exit 1; }
for i in $(seq 1 30); do curl -fsS "$QDRANT/readyz" >/dev/null 2>&1 && break; sleep 2; done
curl -fsS -X POST "$QDRANT/collections/$COLLECTION/snapshots/upload?priority=snapshot&wait=true" \
  -F "snapshot=@${SNAPSHOT}"
echo
curl -fsS "$QDRANT/collections/$COLLECTION" | grep -o '"points_count":[0-9]*' \
  || { echo "Restore check failed" >&2; exit 1; }

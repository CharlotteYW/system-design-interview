#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(git -C "$(dirname "${BASH_SOURCE[0]}")" rev-parse --show-toplevel)"
QUESTION_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=/dev/null
source "${REPO_ROOT}/scripts/use-venv.sh"

cd "${QUESTION_DIR}"
docker compose up --build -d

echo "Waiting for http://localhost:8300/healthz ..."
for _ in $(seq 1 90); do
  if curl -sf http://localhost:8300/healthz >/dev/null && curl -s -o /dev/null http://localhost:8301/; then
    echo "YouTube lab is up at http://localhost:8300"
    echo "  S3 API (MinIO):      http://localhost:9000"
    echo "  CDN edge (shield):   http://localhost:8301  slow edge: 8305  no-shield edge: 8303"
    exit 0
  fi
  sleep 2
done

echo "Timed out waiting for the YouTube lab." >&2
docker compose logs --tail 80
exit 1

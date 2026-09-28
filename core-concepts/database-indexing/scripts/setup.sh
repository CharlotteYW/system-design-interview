#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(git -C "$(dirname "${BASH_SOURCE[0]}")" rev-parse --show-toplevel)"
CONCEPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=/dev/null
source "${REPO_ROOT}/scripts/use-venv.sh"

cd "${CONCEPT_DIR}"
docker compose up --build -d

echo "Waiting for http://localhost:8000/healthz ..."
for _ in $(seq 1 90); do
  if curl -sf http://localhost:8000/healthz >/dev/null; then
    echo "Indexing lab is up at http://localhost:8000 — leave it running to read EXPLAIN. Stop later with ./scripts/stop.sh."
    exit 0
  fi
  sleep 1
done

echo "Timed out waiting for the indexing lab." >&2
docker compose logs --tail 80
exit 1

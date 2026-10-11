#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(git -C "$(dirname "${BASH_SOURCE[0]}")" rev-parse --show-toplevel)"
QUESTION_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=/dev/null
source "${REPO_ROOT}/scripts/use-venv.sh"

cd "${QUESTION_DIR}"
docker compose up --build -d

echo "Waiting for http://localhost:8000/healthz ..."
for _ in $(seq 1 60); do
  if curl -sf http://localhost:8000/healthz >/dev/null; then
    echo "News feed is up at http://localhost:8000"
    exit 0
  fi
  sleep 2
done

echo "Timed out waiting for the news feed to become healthy." >&2
docker compose logs --tail 80
exit 1

#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(git -C "$(dirname "${BASH_SOURCE[0]}")" rev-parse --show-toplevel)"
QUESTION_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=/dev/null
source "${REPO_ROOT}/scripts/use-venv.sh"

cd "${QUESTION_DIR}"
docker compose up --build -d

echo "Waiting for http://localhost:8400/healthz ..."
for _ in $(seq 1 90); do
  if curl -sf http://localhost:8400/healthz >/dev/null; then
    # The workers start after the app is healthy; give them a moment to connect.
    sleep 3
    echo "Web crawler lab is up at http://localhost:8400"
    echo "  Services: app, scheduler, fetcher x2 (6 workers each), parser, fakeweb"
    echo "  Stores:   DynamoDB Local, ElasticMQ (SQS), MinIO (S3), Redis, Postgres (race panel only)"
    exit 0
  fi
  sleep 2
done

echo "Timed out waiting for the web crawler lab." >&2
docker compose logs --tail 80
exit 1

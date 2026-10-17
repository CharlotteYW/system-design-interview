#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(git -C "$(dirname "${BASH_SOURCE[0]}")" rev-parse --show-toplevel)"
QUESTION_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=/dev/null
source "${REPO_ROOT}/scripts/use-venv.sh"

cd "${QUESTION_DIR}"
docker compose up --build -d

wait_for() {
  local url="$1" name="$2" tries="$3"
  echo "Waiting for ${name} at ${url} ..."
  for _ in $(seq 1 "${tries}"); do
    if curl -sf "${url}/healthz" >/dev/null; then
      echo "${name} is up at ${url}"
      return 0
    fi
    sleep 2
  done
  echo "Timed out waiting for ${name}." >&2
  docker compose logs --tail 80
  exit 1
}

wait_for http://localhost:8000 "Design 1 (Postgres messages)" 60
# Cassandra needs about a minute before it accepts CQL.
wait_for http://localhost:8001 "Design 2 (Cassandra messages)" 120

echo "Compare both designs at http://localhost:8000/compare"

#!/usr/bin/env bash
# Load test both designs. Resets each lab before and after its run.
set -euo pipefail

REPO_ROOT="$(git -C "$(dirname "${BASH_SOURCE[0]}")" rev-parse --show-toplevel)"
QUESTION_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=/dev/null
source "${REPO_ROOT}/scripts/use-venv.sh"

cd "${QUESTION_DIR}"
python scripts/load_test.py \
  --url "postgres=${CHAT_PG_URL:-http://localhost:8000}" \
  --url "cassandra=${CHAT_CS_URL:-http://localhost:8001}" \
  --concurrency "${LOAD_CONCURRENCY:-1,8,32}" \
  --seconds "${LOAD_SECONDS:-10}"

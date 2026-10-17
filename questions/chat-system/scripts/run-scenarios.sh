#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(git -C "$(dirname "${BASH_SOURCE[0]}")" rev-parse --show-toplevel)"
QUESTION_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=/dev/null
source "${REPO_ROOT}/scripts/use-venv.sh"

cd "${QUESTION_DIR}"
export CHAT_PG_URL="${CHAT_PG_URL:-http://localhost:8000}"
export CHAT_CS_URL="${CHAT_CS_URL:-http://localhost:8001}"

echo "Integration tests against design 1 (${CHAT_PG_URL}) and design 2 (${CHAT_CS_URL})"
python -m pytest tests/test_scenarios.py -v

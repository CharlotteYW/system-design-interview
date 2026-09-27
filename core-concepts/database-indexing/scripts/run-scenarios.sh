#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(git -C "$(dirname "${BASH_SOURCE[0]}")" rev-parse --show-toplevel)"
CONCEPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=/dev/null
source "${REPO_ROOT}/scripts/use-venv.sh"

cd "${CONCEPT_DIR}"
export INDEXING_BASE_URL="${INDEXING_BASE_URL:-http://localhost:8000}"

echo "Integration tests against ${INDEXING_BASE_URL}"
python -m pytest tests/test_integration.py -v

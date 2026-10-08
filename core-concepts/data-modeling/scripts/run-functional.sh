#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(git -C "$(dirname "${BASH_SOURCE[0]}")" rev-parse --show-toplevel)"
CONCEPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=/dev/null
source "${REPO_ROOT}/scripts/use-venv.sh"

cd "${CONCEPT_DIR}"
export API_BASE_URL="${API_BASE_URL:-http://localhost:8000}"

echo "Functional tests against ${API_BASE_URL}"
python -m pytest tests/test_functional.py -v

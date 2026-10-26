#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(git -C "$(dirname "${BASH_SOURCE[0]}")" rev-parse --show-toplevel)"
QUESTION_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=/dev/null
source "${REPO_ROOT}/scripts/use-venv.sh"

cd "${QUESTION_DIR}"
export AC_BASE_URL="${AC_BASE_URL:-http://localhost:8410}"
echo "Functional tests against ${AC_BASE_URL}"
python -m pytest tests/test_functional.py -v -s -p no:cacheprovider

#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(git -C "$(dirname "${BASH_SOURCE[0]}")" rev-parse --show-toplevel)"
QUESTION_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=/dev/null
source "${REPO_ROOT}/scripts/use-venv.sh"

cd "${QUESTION_DIR}"
export CRAWL_BASE_URL="${CRAWL_BASE_URL:-http://localhost:8400}"
echo "Integration tests against ${CRAWL_BASE_URL} (about 4 minutes: real politeness gaps and backoff)"
python -m pytest tests/test_scenarios.py -v -s -p no:cacheprovider

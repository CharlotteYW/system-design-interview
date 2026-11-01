#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(git -C "$(dirname "${BASH_SOURCE[0]}")" rev-parse --show-toplevel)"
QUESTION_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "${REPO_ROOT}/scripts/use-venv.sh"
cd "${QUESTION_DIR}"
python -m pytest tests/test_scenarios.py -v

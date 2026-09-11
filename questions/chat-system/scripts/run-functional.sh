#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(git -C "$(dirname "${BASH_SOURCE[0]}")" rev-parse --show-toplevel)"
QUESTION_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=/dev/null
source "${REPO_ROOT}/scripts/use-venv.sh"

echo "Not implemented yet."
echo "When this question is prepared, this script will run functional tests of user-visible flows:"
echo "  - exercise the real UI and/or the HTTP API the UI uses"
echo "  - cover the core create/read (or equivalent) path end-to-end"
echo "  - a simpler version of a hard feature is OK; skipping the test is not"
exit 1

#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(git -C "$(dirname "${BASH_SOURCE[0]}")" rev-parse --show-toplevel)"
QUESTION_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=/dev/null
source "${REPO_ROOT}/scripts/use-venv.sh"

echo "Not implemented yet."
echo "When this question is prepared, this script will run black-box scenarios against the running stack:"
echo "  - happy path"
echo "  - at least one failure / rejection path"
echo "  - at least one scale-ish or concurrency edge"
exit 1

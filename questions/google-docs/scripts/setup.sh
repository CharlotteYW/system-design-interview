#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(git -C "$(dirname "${BASH_SOURCE[0]}")" rev-parse --show-toplevel)"
QUESTION_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=/dev/null
source "${REPO_ROOT}/scripts/use-venv.sh"

echo "Not implemented yet."
echo "When this question is prepared, this script will:"
echo "  1. Build and start docker compose services"
echo "  2. Wait until the app is healthy"
echo "  3. Apply any seed data needed for scenarios"
exit 1

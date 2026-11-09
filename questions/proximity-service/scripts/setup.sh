#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(git -C "$(dirname "${BASH_SOURCE[0]}")" rev-parse --show-toplevel)"
QUESTION_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=/dev/null
source "${REPO_ROOT}/scripts/use-venv.sh"

cd "${QUESTION_DIR}"
docker compose up --build --detach --wait --wait-timeout 120
curl --fail --silent --show-error --max-time 5 http://127.0.0.1:8430/ >/dev/null
echo "Proximity Service lab is ready at http://127.0.0.1:8430/"

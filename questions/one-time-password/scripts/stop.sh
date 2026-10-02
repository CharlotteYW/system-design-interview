#!/usr/bin/env bash
set -euo pipefail

QUESTION_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${QUESTION_DIR}"
docker compose down
echo "Stopped services for $(basename "${QUESTION_DIR}"). Start again with ./scripts/setup.sh"

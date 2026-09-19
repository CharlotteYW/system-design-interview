#!/usr/bin/env bash
set -euo pipefail

CONCEPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${CONCEPT_DIR}"
if [[ -f docker-compose.yml ]] && grep -qE '^[[:space:]]+build:|^[[:space:]]+image:' docker-compose.yml; then
  docker compose down
  echo "Stopped services for $(basename "${CONCEPT_DIR}"). Start again with ./scripts/setup.sh"
else
  echo "No running demo for $(basename "${CONCEPT_DIR}")."
fi

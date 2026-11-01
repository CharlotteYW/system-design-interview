#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(git -C "$(dirname "${BASH_SOURCE[0]}")" rev-parse --show-toplevel)"
QUESTION_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "${REPO_ROOT}/scripts/use-venv.sh"
cd "${QUESTION_DIR}"
./scripts/prepare-tls.sh
docker compose up --build -d
for _ in $(seq 1 80); do
  if curl --cacert .certs/ca.crt -fsS https://localhost:8420/healthz >/dev/null 2>&1; then
    echo 'Drive lab: https://localhost:8420'
    echo 'For browser trust on macOS, run scripts/trust-local-cert.sh after first setup or renewal.'
    echo 'It trusts this exact server certificate for user SSL; verification stays enabled.'
    exit 0
  fi
  sleep 2
done
docker compose logs --tail 40
exit 1

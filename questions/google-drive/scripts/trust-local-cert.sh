#!/usr/bin/env bash
set -euo pipefail
QUESTION_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ "$(uname -s)" != Darwin ]]; then
  echo 'This helper configures macOS user trust only.' >&2
  exit 1
fi
CERT="${QUESTION_DIR}/.certs/public.crt"
if [[ ! -f "${CERT}" ]]; then
  echo 'Run scripts/prepare-tls.sh first.' >&2
  exit 1
fi
openssl verify -CAfile "${QUESTION_DIR}/.certs/ca.crt" -purpose sslserver \
  -verify_hostname localhost "${CERT}"
if ! openssl x509 -in "${CERT}" -noout -ext basicConstraints | grep -q 'CA:FALSE'; then
  echo 'Refusing to trust a CA certificate as the lab server.' >&2
  exit 1
fi
openssl x509 -in "${CERT}" -noout -subject -fingerprint -sha256
echo 'Trust scope: current macOS user; SSL; this exact non-CA server certificate.'
echo 'macOS may ask you to authorize this Keychain change.'
/usr/bin/security add-trusted-cert -r trustAsRoot -p ssl \
  -k "${HOME}/Library/Keychains/login.keychain-db" "${CERT}"
cp "${CERT}" "${QUESTION_DIR}/.local-ca/trusted-server.pem"
echo 'Exact server certificate trusted. Reload the browser page.'

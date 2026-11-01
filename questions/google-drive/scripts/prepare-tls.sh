#!/usr/bin/env bash
set -euo pipefail
QUESTION_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${QUESTION_DIR}"
umask 077
mkdir -p .certs .local-ca

# Keep the signing key outside .certs: only .certs is mounted into containers.
if [[ ! -f .local-ca/rootCA.pem || ! -f .local-ca/rootCA-key.pem ]]; then
  openssl req -x509 -newkey rsa:3072 -nodes -days 3650 \
    -keyout .local-ca/rootCA-key.pem -out .local-ca/rootCA.pem \
    -subj '/CN=Drive Study Local CA/O=Local system design lab' \
    -addext 'basicConstraints=critical,CA:TRUE,pathlen:0' \
    -addext 'keyUsage=critical,keyCertSign,cRLSign' >/dev/null 2>&1
fi
cp .local-ca/rootCA.pem .certs/ca.crt

if [[ ! -f .certs/public.crt || ! -f .certs/private.key ]] || \
   ! openssl verify -CAfile .certs/ca.crt .certs/public.crt >/dev/null 2>&1 || \
   ! openssl x509 -checkend 2592000 -noout -in .certs/public.crt >/dev/null; then
  openssl req -new -newkey rsa:2048 -nodes -keyout .certs/private.key \
    -out .local-ca/server.csr -subj '/CN=localhost/O=Drive Study Lab' >/dev/null 2>&1
  cat > .local-ca/server.ext <<'EOF'
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
subjectAltName=DNS:localhost,DNS:app,DNS:storage,DNS:edge,DNS:postgres,DNS:redis,DNS:minio,IP:127.0.0.1,IP:::1
subjectKeyIdentifier=hash
authorityKeyIdentifier=keyid,issuer
EOF
  openssl x509 -req -in .local-ca/server.csr -CA .local-ca/rootCA.pem \
    -CAkey .local-ca/rootCA-key.pem -CAcreateserial -days 365 -sha256 \
    -extfile .local-ca/server.ext -out .certs/public.crt >/dev/null 2>&1
fi
chmod 600 .certs/private.key .local-ca/rootCA-key.pem
chmod 644 .certs/public.crt .certs/ca.crt
openssl verify -CAfile .certs/ca.crt -verify_hostname localhost .certs/public.crt

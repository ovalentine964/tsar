#!/usr/bin/env bash
# ============================================================
# TSAR — Generate Self-Signed TLS Certificates
# ============================================================
# For production, replace with certificates from a real CA
# (e.g., Let's Encrypt via certbot).
#
# Usage:
#   chmod +x deploy/tls/generate-self-signed.sh
#   ./deploy/tls/generate-self-signed.sh
#
# Output:
#   deploy/tls/certs/server.crt
#   deploy/tls/certs/server.key
# ============================================================

set -euo pipefail

CERT_DIR="$(cd "$(dirname "$0")" && pwd)/certs"
mkdir -p "$CERT_DIR"

DOMAIN="${TSAR_TLS_DOMAIN:-localhost}"
DAYS="${TSAR_TLS_DAYS:-365}"

echo "🔐 Generating self-signed TLS certificate..."
echo "   Domain: $DOMAIN"
echo "   Valid for: $DAYS days"
echo "   Output: $CERT_DIR/"

openssl req -x509 -newkey rsa:4096 \
    -keyout "$CERT_DIR/server.key" \
    -out "$CERT_DIR/server.crt" \
    -days "$DAYS" \
    -nodes \
    -subj "/CN=$DOMAIN/O=TSAR/C=US" \
    -addext "subjectAltName=DNS:$DOMAIN,DNS:localhost,IP:127.0.0.1"

chmod 600 "$CERT_DIR/server.key"
chmod 644 "$CERT_DIR/server.crt"

echo "✅ TLS certificates generated:"
echo "   Certificate: $CERT_DIR/server.crt"
echo "   Private key: $CERT_DIR/server.key"
echo ""
echo "⚠️  Self-signed certs are for development/testing only."
echo "   For production, use Let's Encrypt or a commercial CA."

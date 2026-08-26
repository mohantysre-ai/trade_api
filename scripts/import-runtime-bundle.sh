#!/usr/bin/env sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"
BUNDLE=${1:-}
[ -n "$BUNDLE" ] && [ -f "$BUNDLE" ] || { echo "Usage: $0 /path/to/sigq-runtime.tar.gz[.enc]" >&2; exit 2; }

STAGE=$(mktemp -d)
PLAIN="$BUNDLE"
cleanup() { rm -rf "$STAGE"; }
trap cleanup EXIT INT TERM

case "$BUNDLE" in
  *.enc)
    [ -n "${SIGQ_BUNDLE_PASSWORD:-}" ] || { echo "Set SIGQ_BUNDLE_PASSWORD to decrypt the bundle." >&2; exit 1; }
    command -v openssl >/dev/null 2>&1 || { echo "openssl is required." >&2; exit 1; }
    PLAIN="$STAGE/runtime.tar.gz"
    openssl enc -d -aes-256-cbc -pbkdf2 -in "$BUNDLE" -out "$PLAIN" -pass env:SIGQ_BUNDLE_PASSWORD
    ;;
esac

tar xzf "$PLAIN" -C "$STAGE"
[ -s "$STAGE/secrets/backend.env" ] || { echo "Bundle is missing backend.env" >&2; exit 1; }
[ -s "$STAGE/secrets/cloudflare-credentials.json" ] || { echo "Bundle is missing Cloudflare credentials" >&2; exit 1; }

install -m 600 "$STAGE/secrets/backend.env" backend/.env
install -m 600 "$STAGE/secrets/cloudflare-credentials.json" config/cloudflare/credentials.json

# Create deterministic project volumes without pulling/starting application images.
for volume in iros-desk-state iros-backend-data iros-eod-archive; do
  docker volume create --label com.docker.compose.project=sigq \
    --label "com.docker.compose.volume=${volume}" "sigq_${volume}" >/dev/null
  archive="$STAGE/volumes/${volume}.tar.gz"
  [ -f "$archive" ] || continue
  docker run --rm \
    -v "sigq_${volume}:/target" \
    -v "$STAGE/volumes:/backup:ro" \
    alpine:3.21 sh -c "find /target -mindepth 1 -maxdepth 1 -exec rm -rf {} + && tar xzf /backup/${volume}.tar.gz -C /target"
done

echo "Runtime restored. Start everything with: scripts/deploy-portable.sh --build"

#!/usr/bin/env sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"
OUT=${1:-"$ROOT/sigq-runtime-$(date +%Y%m%d-%H%M%S).tar.gz"}
STAGE=$(mktemp -d)
STOPPED=0

cleanup() {
  if [ "$STOPPED" = 1 ]; then docker compose start market-api ai-news >/dev/null 2>&1 || true; fi
  rm -rf "$STAGE"
}
trap cleanup EXIT INT TERM

command -v docker >/dev/null 2>&1 || { echo "Docker is required." >&2; exit 1; }
[ -s backend/.env ] || { echo "Missing backend/.env" >&2; exit 1; }
[ -s config/cloudflare/credentials.json ] || { echo "Missing Cloudflare credentials.json" >&2; exit 1; }

mkdir -p "$STAGE/secrets" "$STAGE/volumes"
cp backend/.env "$STAGE/secrets/backend.env"
cp config/cloudflare/credentials.json "$STAGE/secrets/cloudflare-credentials.json"
chmod 600 "$STAGE/secrets/"*

# Stop writers briefly so JSON and EOD archives are internally consistent.
if docker compose ps --status running --services | grep -Eq '^(market-api|ai-news)$'; then
  docker compose stop market-api ai-news >/dev/null
  STOPPED=1
fi

for volume in iros-desk-state iros-backend-data iros-eod-archive; do
  docker volume inspect "sigq_${volume}" >/dev/null 2>&1 || { echo "Missing Docker volume sigq_${volume}." >&2; exit 1; }
  docker run --rm \
    -v "sigq_${volume}:/source:ro" \
    -v "$STAGE/volumes:/backup" \
    alpine:3.21 sh -c "tar czf /backup/${volume}.tar.gz -C /source ."
done

cat > "$STAGE/manifest.txt" <<EOF
bundleVersion=1
createdAt=$(date -u +%Y-%m-%dT%H:%M:%SZ)
gitCommit=$(git rev-parse HEAD 2>/dev/null || echo unknown)
composeProject=sigq
EOF

tar czf "$OUT" -C "$STAGE" .
chmod 600 "$OUT"

if [ -n "${SIGQ_BUNDLE_PASSWORD:-}" ]; then
  command -v openssl >/dev/null 2>&1 || { echo "openssl is required for encrypted export." >&2; exit 1; }
  openssl enc -aes-256-cbc -pbkdf2 -salt -in "$OUT" -out "$OUT.enc" -pass env:SIGQ_BUNDLE_PASSWORD
  rm -f "$OUT"
  chmod 600 "$OUT.enc"
  echo "Encrypted runtime bundle: $OUT.enc"
else
  echo "Runtime bundle: $OUT"
  echo "WARNING: it contains live credentials. Set SIGQ_BUNDLE_PASSWORD before export to encrypt it."
fi

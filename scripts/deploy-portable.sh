#!/usr/bin/env sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"

MODE=${1:---build}
case "$MODE" in
  --pull|--build) ;;
  *) echo "Usage: $0 [--pull|--build]" >&2; exit 2 ;;
esac

command -v docker >/dev/null 2>&1 || { echo "Docker is required." >&2; exit 1; }
docker info >/dev/null 2>&1 || { echo "Docker daemon is not running." >&2; exit 1; }
docker compose version >/dev/null 2>&1 || { echo "Docker Compose v2 is required." >&2; exit 1; }

[ -s backend/.env ] || { echo "Missing backend/.env (copy backend/.env.example and add credentials)." >&2; exit 1; }
for key in ANGEL_API_KEY ANGEL_CLIENT_ID ANGEL_TOTP_SECRET; do
  grep -Eq "^${key}=.+" backend/.env || { echo "backend/.env is missing $key." >&2; exit 1; }
done
grep -Eq '^ANGEL_(MPIN|PASSWORD)=.+' backend/.env || { echo "backend/.env needs ANGEL_MPIN or ANGEL_PASSWORD." >&2; exit 1; }
[ -s config/cloudflare/credentials.json ] || {
  echo "Missing config/cloudflare/credentials.json. Export/import the runtime bundle or copy the iros-desk tunnel credential." >&2
  exit 1
}
grep -q '"TunnelID"' config/cloudflare/credentials.json || {
  echo "Cloudflare credentials.json does not contain TunnelID." >&2
  exit 1
}

docker compose --profile tunnel config --quiet

if [ "$MODE" = "--pull" ]; then
  docker compose --profile tunnel pull
  docker compose --profile tunnel up -d --no-build --remove-orphans --wait --wait-timeout 300
else
  docker compose --profile tunnel up -d --build --remove-orphans --wait --wait-timeout 300
fi

docker compose --profile tunnel ps
docker compose exec -T market-api python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=5)"
docker compose exec -T ai-news python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8001/health', timeout=5)"
docker compose exec -T frontend node -e "fetch('http://127.0.0.1:3000/').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"
echo "SIGQ is healthy: local http://127.0.0.1:3000 · public https://sigq.in"

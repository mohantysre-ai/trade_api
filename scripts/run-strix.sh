#!/usr/bin/env bash
set -euo pipefail

scan_scope="${1:-${STRIX_SCAN_SCOPE:-repository}}"
scan_mode="${STRIX_SCAN_MODE:-quick}"
max_budget="${STRIX_MAX_BUDGET:-10}"
max_turns="${STRIX_MAX_TURNS:-300}"
repo_target="${STRIX_REPO_TARGET:-.}"
web_target="${STRIX_WEB_TARGET:-}"
allowed_hosts="${STRIX_ALLOWED_HOSTS:-sigq.in,www.sigq.in}"
authenticated="${STRIX_AUTHENTICATED:-false}"
instruction_source="${STRIX_INSTRUCTION_FILE:-.strix/pentest-instructions.md}"

case "$scan_scope" in
  repository|web|multi) ;;
  *) echo "Invalid scan scope: $scan_scope (use repository, web, or multi)" >&2; exit 2 ;;
esac

case "$scan_mode" in
  quick|standard|deep) ;;
  *) echo "Invalid scan mode: $scan_mode (use quick, standard, or deep)" >&2; exit 2 ;;
esac

if ! [[ "$max_budget" =~ ^[0-9]+([.][0-9]+)?$ ]] || ! [[ "$max_turns" =~ ^[1-9][0-9]*$ ]]; then
  echo "STRIX_MAX_BUDGET and STRIX_MAX_TURNS must be positive numbers" >&2
  exit 2
fi

command -v strix >/dev/null || { echo "strix is not installed" >&2; exit 2; }
command -v docker >/dev/null || { echo "Docker is required by Strix" >&2; exit 2; }
docker info >/dev/null 2>&1 || { echo "Docker daemon is not available" >&2; exit 2; }
test -f "$instruction_source" || { echo "Missing instruction file: $instruction_source" >&2; exit 2; }

validate_web_target() {
  TARGET_URL="$web_target" ALLOWED_HOSTS="$allowed_hosts" python - <<'PY'
import os
import sys
from urllib.parse import urlsplit

target = os.environ.get("TARGET_URL", "").strip()
allowed = {item.strip().lower().rstrip(".") for item in os.environ.get("ALLOWED_HOSTS", "").split(",") if item.strip()}
try:
    parsed = urlsplit(target)
    host = (parsed.hostname or "").lower().rstrip(".")
    port = parsed.port
except ValueError as exc:
    raise SystemExit(f"Invalid STRIX_WEB_TARGET: {exc}")

if parsed.scheme != "https" or not host or parsed.username or parsed.password:
    raise SystemExit("Remote Strix targets must be credential-free HTTPS URLs")
if host not in allowed:
    raise SystemExit(f"Target host {host!r} is not in STRIX_ALLOWED_HOSTS")
if port not in (None, 443):
    raise SystemExit("Only the authorized HTTPS port 443 is allowed")
if parsed.fragment:
    raise SystemExit("Target URLs must not contain fragments")
print(f"Authorized Strix web target: {target}")
PY
}

if [[ "$scan_scope" == "web" || "$scan_scope" == "multi" ]]; then
  test -n "$web_target" || { echo "STRIX_WEB_TARGET is required for $scan_scope scans" >&2; exit 2; }
  validate_web_target
fi

runtime_instruction="$(mktemp)"
cleanup() {
  chmod 600 "$runtime_instruction" 2>/dev/null || true
  : > "$runtime_instruction"
}
trap cleanup EXIT
chmod 600 "$runtime_instruction"
cp "$instruction_source" "$runtime_instruction"

if [[ "$authenticated" == "true" ]]; then
  : "${STRIX_TEST_USERNAME:?STRIX_TEST_USERNAME is required for authenticated testing}"
  : "${STRIX_TEST_PASSWORD:?STRIX_TEST_PASSWORD is required for authenticated testing}"
  INSTRUCTION_PATH="$runtime_instruction" python - <<'PY'
import os
from pathlib import Path

path = Path(os.environ["INSTRUCTION_PATH"])
with path.open("a", encoding="utf-8") as handle:
    handle.write("\n## Authorized test-account login\n\n")
    handle.write(f"Username: {os.environ['STRIX_TEST_USERNAME']}\n")
    handle.write(f"Password: {os.environ['STRIX_TEST_PASSWORD']}\n")
    login_url = os.environ.get("STRIX_LOGIN_URL", "").strip()
    if login_url:
        handle.write(f"Login URL: {login_url}\n")
    handle.write("Use this account only for non-destructive authenticated verification.\n")
PY
elif [[ "$authenticated" != "false" ]]; then
  echo "STRIX_AUTHENTICATED must be true or false" >&2
  exit 2
fi

args=(
  --non-interactive
  --scan-mode "$scan_mode"
  --max-budget "$max_budget"
  --max-turns "$max_turns"
  --instruction-file "$runtime_instruction"
)

case "$scan_scope" in
  repository)
    args+=(--target "$repo_target")
    ;;
  web)
    args+=(--target "$web_target")
    ;;
  multi)
    args+=(--target "$repo_target" --target "$web_target")
    ;;
esac

if [[ "$scan_scope" != "web" && -n "${STRIX_SCOPE_MODE:-}" ]]; then
  args+=(--scope-mode "$STRIX_SCOPE_MODE")
fi
if [[ "$scan_scope" != "web" && -n "${STRIX_DIFF_BASE:-}" ]]; then
  args+=(--diff-base "$STRIX_DIFF_BASE")
fi

echo "Starting authorized Strix $scan_scope scan (mode=$scan_mode, budget=$max_budget, turns=$max_turns)"
strix "${args[@]}"

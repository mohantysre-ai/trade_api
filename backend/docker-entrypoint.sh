#!/bin/sh
set -eu
mkdir -p /app/state /app/backend/app/data/eod /app/backend/app/services/eod_archive
[ -f /app/state/trade_api_snapshot.json ] || printf '%s\n' '{}' > /app/state/trade_api_snapshot.json
[ -f /app/state/fixed_trade_plan.json ] || printf '%s\n' '{}' > /app/state/fixed_trade_plan.json
[ -f /app/state/alert_history.json ] || printf '%s\n' '[]' > /app/state/alert_history.json
[ -f /app/state/last_market_snapshot.json ] || printf '%s\n' '{}' > /app/state/last_market_snapshot.json
[ -f /app/state/intraday_session.json ] || printf '%s\n' '{}' > /app/state/intraday_session.json
[ -f /app/state/swing_session.json ] || printf '%s\n' '{}' > /app/state/swing_session.json
exec "$@"

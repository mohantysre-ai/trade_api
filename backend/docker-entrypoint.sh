#!/bin/sh
set -eu

seed_if_empty() {
    _src="$1"
    _dst="$2"
    if [ -d "$_src" ]; then
        mkdir -p "$_dst"
        if [ -z "$(find "$_dst" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)" ]; then
            cp -a "$_src"/. "$_dst"/
        fi
    fi
}

seed_state_files() {
    _src_dir="$1"
    _dst_dir="$2"
    if [ -d "$_src_dir" ]; then
        mkdir -p "$_dst_dir"
        for f in "$_src_dir"/*.json "$_src_dir"/*.lock; do
            [ -f "$f" ] || continue
            _base=$(basename "$f")
            if [ ! -f "$_dst_dir/$_base" ]; then
                cp -a "$f" "$_dst_dir/$_base"
            fi
        done
    fi
}

seed_if_empty /opt/seed/data /app/backend/app/data
seed_if_empty /opt/seed/archive /app/backend/app/services/eod_archive
seed_state_files /opt/seed/state /app/state

[ -f /app/state/trade_api_snapshot.json ] || printf '%s\n' '{}' > /app/state/trade_api_snapshot.json
[ -f /app/state/fixed_trade_plan.json ] || printf '%s\n' '{}' > /app/state/fixed_trade_plan.json
[ -f /app/state/alert_history.json ] || printf '%s\n' '[]' > /app/state/alert_history.json
[ -f /app/state/last_market_snapshot.json ] || printf '%s\n' '{}' > /app/state/last_market_snapshot.json
[ -f /app/state/intraday_session.json ] || printf '%s\n' '{}' > /app/state/intraday_session.json
[ -f /app/state/swing_session.json ] || printf '%s\n' '{}' > /app/state/swing_session.json
exec "$@"

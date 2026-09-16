from app.services.swing_session import _read_json, _matrix_snapshot_path, _swing_screen_rows
import json

snap = _read_json(_matrix_snapshot_path())
stocks = snap.get('stocks', [])
by_ticker = {}
for s in stocks:
    sym = str(s.get('ticker') or s.get('symbol') or '').upper().strip()
    if sym:
        by_ticker[sym] = s

# Check dhanSwingPicks symbols in stocks
dhan = snap.get('dhanSwingPicks', {})
for pick in dhan.get('picks', []):
    sym = pick.get('symbol')
    if sym in by_ticker:
        stock = by_ticker[sym]
        side = stock.get('side') or stock.get('signalSide') or stock.get('tradeSide') or stock.get('direction') or stock.get('deterministicSide') or stock.get('deterministic_side')
        print(f'{sym}: side={side}, passesHard={stock.get("passesHardFilters")}, passesQuality={stock.get("passesQualityFilters")}, verdict={stock.get("verdict")}, score={stock.get("score")}')
    else:
        print(f'{sym}: NOT IN STOCKS ARRAY')

print('\n=== swing_screen_rows ===')
screen = _swing_screen_rows(snap)
print(f'Screen rows: {len(screen)}')
for row in screen[:10]:
    sym = str(row.get('ticker') or row.get('symbol') or '').upper().strip()
    side = row.get('side') or row.get('signalSide') or row.get('tradeSide') or row.get('direction') or row.get('deterministicSide') or row.get('deterministic_side')
    print(f'{sym}: side={side}, passesHard={row.get("passesHardFilters")}, passesQuality={row.get("passesQualityFilters")}, verdict={row.get("verdict")}')
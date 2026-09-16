from app.services.swing_session import _read_json, _matrix_snapshot_path, _evaluate_swing_buy_contract, _hydrate_swing_contract_row
import json

snap = _read_json(_matrix_snapshot_path())
quotes = snap.get('stockQuotes', {})
dhan = snap.get('dhanSwingPicks', {})

print('=== Evaluating 33 Dhan Scanner LONG candidates against Swing BUY Contract ===\n')

for pick in dhan.get('picks', []):
    sym = pick.get('symbol')
    quote = quotes.get(sym, {})
    
    # Create a row with scanner data + quote data
    row = {
        **pick,
        'symbol': sym,
        'ticker': sym,
        'ltp': quote.get('ltp') or pick.get('scanLtp') or pick.get('buyAbove'),
        'ltpRaw': quote.get('ltpRaw'),
        'delta': quote.get('delta'),
        'vwap': quote.get('vwap'),
        'ema9': quote.get('ema9'),
        'rsi': quote.get('rsi'),
        'oi': quote.get('oi'),
        'prevOi': quote.get('prevOi'),
        'oiSetup': quote.get('oiSetup'),
        'pivotR1Breakout': quote.get('pivotR1Breakout'),
        'rsiPivotBreak': quote.get('rsiPivotBreak'),
        'breakoutPass': quote.get('breakoutPass'),
    }
    
    eligible, evidence, reasons = _evaluate_swing_buy_contract(row)
    status = 'QUALIFIED' if eligible else 'REJECTED'
    print(f'{sym}: {status}')
    if not eligible:
        for r in reasons:
            print(f'  - {r}')
    print()

# Also check ACMESOLAR from ledger
print('\n=== ACMESOLAR (ledger) ===')
ledger = snap.get('terminalIntelligence', {}).get('ledger_stocks', [])
for item in ledger:
    sym = str(item.get('ticker') or item.get('symbol') or '').upper().strip()
    quote = quotes.get(sym, {})
    row = {**item, 'symbol': sym, 'ticker': sym}
    eligible, evidence, reasons = _evaluate_swing_buy_contract(row)
    status = 'QUALIFIED' if eligible else 'REJECTED'
    print(f'{sym}: {status}')
    if not eligible:
        for r in reasons:
            print(f'  - {r}')
    print(f'  Evidence: passesHard={evidence.get("passesHardFilters")}, passesQuality={evidence.get("passesQualityFilters")}, vwap={evidence.get("vwap")}, ema9={evidence.get("ema9")}, rsi={evidence.get("rsi")}, oiSetup={evidence.get("oiSetup")}, breakoutPass={evidence.get("breakoutPass")}, dayChangePct={evidence.get("dayChangePct")}')
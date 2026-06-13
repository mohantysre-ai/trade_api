import json

d = json.load(open('d:/trade_api/tmp_api_debug.json'))
ti = d.get('terminalIntelligence', {})
ls = ti.get('ledger_stocks', [])
print(f'Ledger stocks count: {len(ls)}')
for s in ls[:5]:
    reason = repr(s.get('selection_reason', ''))[:100]
    action = s.get('action', '')
    print(f'  {s["ticker"]}: reason={reason}  action={action}')

# Also check active_factor_hub
hub = ti.get('active_factor_hub', {})
print(f'\nHub thesis: {repr(hub.get("thesis", "N/A"))[:100]}')
print(f'Hub selection_reason: {repr(hub.get("selection_reason", "N/A"))[:100]}')
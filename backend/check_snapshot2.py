from app.services.swing_session import _read_json, _matrix_snapshot_path
snap = _read_json(_matrix_snapshot_path())
ti = snap.get('terminalIntelligence', {})
print('=== TI Keys ===')
for k, v in ti.items():
    if isinstance(v, list):
        print(f'{k}: {len(v)} items')
    else:
        print(f'{k}: {type(v)}')

# Check if there's scanner data somewhere else
print('\n=== Checking all keys for scanner ===')
for k, v in snap.items():
    if 'scan' in k.lower() or 'long' in k.lower() or 'short' in k.lower():
        if isinstance(v, list):
            print(f'{k}: {len(v)} items')
            for item in v[:5]:
                print(f'  {item}')
        else:
            print(f'{k}: {v}')

# Check ledger_stocks
print('\n=== Ledger Stocks ===')
ledger = ti.get('ledger_stocks', [])
for item in ledger:
    print(f'  {item}')
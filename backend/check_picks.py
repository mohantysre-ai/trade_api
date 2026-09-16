from app.services.swing_session import lock_swing_session, _swing_universe_diagnostics, _picks_from_asset_matrix
import json

# First check the diagnostics
print("=== Diagnostics ===")
diagnostics = _swing_universe_diagnostics()
print(json.dumps(diagnostics, indent=2))

# Check what _picks_from_asset_matrix returns
print("\n=== Picks from Asset Matrix ===")
candidates, src = _picks_from_asset_matrix()
print(f"Source: {src}")
print(f"Candidates count: {len(candidates)}")
for c in candidates:
    print(f"  {c.get('symbol')}: side={c.get('side')}, source={c.get('_candidateSource')}, passesHard={c.get('passesHardFilters')}, passesQuality={c.get('passesQualityFilters')}")
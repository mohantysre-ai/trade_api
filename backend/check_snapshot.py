from app.services.swing_session import _read_json, _matrix_snapshot_path
snap = _read_json(_matrix_snapshot_path())
for s in snap.get('stocks', []):
    side = s.get('side') or s.get('signalSide') or s.get('tradeSide') or s.get('direction') or s.get('deterministicSide') or s.get('deterministic_side')
    if side:
        print(f'{s.get("ticker")}: side={side}, passesHard={s.get("passesHardFilters")}, passesQuality={s.get("passesQualityFilters")}, verdict={s.get("verdict")}')
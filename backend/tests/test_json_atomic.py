import os

from app.services.json_atomic import atomic_update_json, atomic_write_json, load_json_with_fallback


def test_atomic_update_patches_latest_disk_not_stale_memory(tmp_path):
    path = tmp_path / "last_market_snapshot.json"
    atomic_write_json(path, {"universe": ["AAA", "BBB"], "stockQuotes": {"AAA": {"ltpRaw": 1}}})

    def _mutator(disk: dict) -> dict:
        quotes = dict(disk.get("stockQuotes") or {})
        quotes["CCC"] = {"ltpRaw": 9, "intraday": {"data_source": "daily_candles", "atr_pct": 2.1}}
        disk["stockQuotes"] = quotes
        return disk

    # Simulate a refresh that finished after the GET loaded an older document.
    atomic_write_json(
        path,
        {"universe": ["AAA", "BBB", "DDD"], "stockQuotes": {"AAA": {"ltpRaw": 1}, "DDD": {"ltpRaw": 4}}},
    )
    atomic_update_json(path, _mutator)
    out = load_json_with_fallback(path)
    assert out["universe"] == ["AAA", "BBB", "DDD"]
    assert "DDD" in out["stockQuotes"]
    assert out["stockQuotes"]["CCC"]["intraday"]["atr_pct"] == 2.1


def test_atomic_update_does_not_wipe_universe_on_corrupt_load(tmp_path):
    path = tmp_path / "last_market_snapshot.json"
    atomic_write_json(path, {"universe": ["AAA", "BBB", "DDD"], "stockQuotes": {"AAA": {"ltpRaw": 1}}})
    path.write_text("{not-json", encoding="utf-8")
    path.with_suffix(path.suffix + ".new").unlink(missing_ok=True)
    path.with_suffix(path.suffix + ".bak").unlink(missing_ok=True)

    def _mutator(disk: dict) -> dict:
        disk["stockQuotes"] = {"CCC": {"ltpRaw": 9}}
        return disk

    try:
        atomic_update_json(path, _mutator)
        raised = False
    except Exception:
        raised = True
    assert raised
    assert path.read_text(encoding="utf-8").startswith("{not-json")


def test_load_prefers_newer_new_sidecar(tmp_path):
    path = tmp_path / "last_market_snapshot.json"
    atomic_write_json(path, {"universe": ["OLD"], "stockQuotes": {"AAA": {"ltpRaw": 1}}})
    new_path = path.with_suffix(path.suffix + ".new")
    new_path.write_text(
        '{"universe": ["NEW"], "stockQuotes": {"BBB": {"ltpRaw": 2}}}',
        encoding="utf-8",
    )
    later = path.stat().st_mtime + 10
    os.utime(new_path, (later, later))
    out = load_json_with_fallback(path)
    assert out["universe"] == ["NEW"]
    assert "BBB" in out["stockQuotes"]

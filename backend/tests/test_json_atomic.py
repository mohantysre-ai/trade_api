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

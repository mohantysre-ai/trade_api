from pathlib import Path


def test_swing_refresh_is_angel_first_and_intraday750_scoped():
    src = Path("app/services/angel_one_feed.py").read_text(encoding="utf-8")
    assert 'swing_hunt = reason == "swing_entry_hunt"' in src
    assert 'INTRADAY_750_LABEL\n        if swing_hunt' in src
    assert 'angel_first_quotes=swing_hunt' in src
    assert 'interval="ONE_HOUR" if angel_first_quotes else "FIVE_MINUTE"' in src
    assert 'timeframe="1h" if angel_first_quotes else "5m"' in src
    assert 'pricePriority": "ANGEL_FIRST_SWING_HUNT"' in src


def test_global_quote_failover_default_is_unchanged():
    src = Path("app/services/market_data_provider.py").read_text(encoding="utf-8")
    assert 'NSE primary, Dhan missing-symbol fallback, then Angel final fallback' in src

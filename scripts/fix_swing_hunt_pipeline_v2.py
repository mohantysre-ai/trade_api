from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)

# Angel-first price snapshot is scoped ONLY to swing_entry_hunt. Existing global
# NSE/Dhan/Angel failover behavior remains unchanged for other consumers.
p = Path('backend/app/services/angel_one_feed.py')
text = p.read_text(encoding='utf-8')
text = replace_once(
    text,
    'def run_scheduled_live_refresh(*, reason: str = "scheduled_live_refresh") -> dict[str, Any]:\n    """Live Angel/Yahoo/RSS refresh with LLM day-lock reuse (no force LLM)."""\n    log = logging.getLogger(__name__)\n    pool = (os.getenv("MARKET_PREWORK_POOL") or NIFTY_500_LABEL).strip() or NIFTY_500_LABEL\n',
    'def run_scheduled_live_refresh(*, reason: str = "scheduled_live_refresh") -> dict[str, Any]:\n    """Live quote/candle refresh with LLM day-lock reuse (no force LLM)."""\n    log = logging.getLogger(__name__)\n    swing_hunt = reason == "swing_entry_hunt"\n    pool = NIFTY_500_LABEL if swing_hunt else ((os.getenv("MARKET_PREWORK_POOL") or NIFTY_500_LABEL).strip() or NIFTY_500_LABEL)\n',
    'scheduled refresh swing mode',
)
text = replace_once(
    text,
    '            force_llm_refresh=False,\n        )\n',
    '            force_llm_refresh=False,\n            angel_first_quotes=swing_hunt,\n        )\n',
    'scheduled refresh flag',
)
text = replace_once(
    text,
    'def _build_payload_from_live_data(\n    client: AngelOneClient,\n    pool_name: str | None = None,\n    custom_prompt: str | None = None,\n    force_llm_refresh: bool = False,\n    prior_snapshot: dict[str, Any] | None = None,\n    on_progress: Callable[[str], None] | None = None,\n) -> dict[str, Any]:\n',
    'def _build_payload_from_live_data(\n    client: AngelOneClient,\n    pool_name: str | None = None,\n    custom_prompt: str | None = None,\n    force_llm_refresh: bool = False,\n    prior_snapshot: dict[str, Any] | None = None,\n    on_progress: Callable[[str], None] | None = None,\n    angel_first_quotes: bool = False,\n) -> dict[str, Any]:\n',
    'live payload signature',
)
old_quote = '    stock_quotes_raw, quote_coverage = _fetch_stock_quotes_with_coverage(client, stock_universe)\n'
new_quote = '''    if angel_first_quotes:\n        # Swing contract: request every resolved Nifty 500 quote from Angel One\n        # first. Only missing Angel symbols use the existing provider failover.\n        angel_rows = client.fetch_batch_quotes(stock_universe)\n        stock_quotes_raw = {\n            str(symbol).upper(): {**dict(row), "quoteProvider": "angel"}\n            for symbol, row in angel_rows.items()\n            if isinstance(row, dict)\n        }\n        missing_instruments = [inst for inst in stock_universe if inst.key not in stock_quotes_raw]\n        fallback_rows: dict[str, dict[str, Any]] = {}\n        fallback_meta: dict[str, Any] = {}\n        if missing_instruments:\n            fallback_rows, fallback_meta = _fetch_stock_quotes_with_coverage(client, missing_instruments)\n            for symbol, row in fallback_rows.items():\n                stock_quotes_raw.setdefault(symbol, row)\n        expected = len(stock_universe)\n        received = len(stock_quotes_raw)\n        coverage_pct = round((received / expected * 100.0) if expected else 0.0, 2)\n        providers = {"angel": len(angel_rows), "nse": 0, "dhan": 0}\n        for provider, count in (fallback_meta.get("providers") or {}).items():\n            providers[provider] = providers.get(provider, 0) + int(count or 0)\n        quote_coverage = {\n            "expected": expected,\n            "received": received,\n            "coveragePct": coverage_pct,\n            "selectionAllowed": bool(expected and coverage_pct >= 99.0),\n            "providers": providers,\n            "missingSymbols": [inst.key for inst in stock_universe if inst.key not in stock_quotes_raw],\n            "pricePriority": "ANGEL_FIRST_SWING_HUNT",\n        }\n    else:\n        stock_quotes_raw, quote_coverage = _fetch_stock_quotes_with_coverage(client, stock_universe)\n'''
text = replace_once(text, old_quote, new_quote, 'angel-first quote branch')
text = replace_once(
    text,
    'def build_market_payload(\n    client: AngelOneClient,\n    pool_name: str | None = None,\n    force_refresh: bool = False,\n    custom_prompt: str | None = None,\n    allow_fallback: bool = True, # If live fetch fails, allow falling back to snapshot\n    prefer_cache: bool = False, # If true, try cache first, then live if cache is empty/stale\n    force_llm_refresh: bool = False,  # When false, reuse day-locked / TTL-fresh snapshot AI\n    on_progress: Callable[[str], None] | None = None,\n) -> dict[str, Any]:\n',
    'def build_market_payload(\n    client: AngelOneClient,\n    pool_name: str | None = None,\n    force_refresh: bool = False,\n    custom_prompt: str | None = None,\n    allow_fallback: bool = True, # If live fetch fails, allow falling back to snapshot\n    prefer_cache: bool = False, # If true, try cache first, then live if cache is empty/stale\n    force_llm_refresh: bool = False,  # When false, reuse day-locked / TTL-fresh snapshot AI\n    on_progress: Callable[[str], None] | None = None,\n    angel_first_quotes: bool = False,\n) -> dict[str, Any]:\n',
    'build market signature',
)
text = replace_once(
    text,
    '            prior_snapshot=snapshot,\n            on_progress=on_progress,\n        )\n',
    '            prior_snapshot=snapshot,\n            on_progress=on_progress,\n            angel_first_quotes=angel_first_quotes,\n        )\n',
    'pass angel-first flag',
)
p.write_text(text, encoding='utf-8')

# Swing hunt freshness and automatic PAPER fills.
p = Path('backend/app/services/swing_session.py')
text = p.read_text(encoding='utf-8')
text = replace_once(
    text,
    '_SWING_MATRIX_REFRESH_TTL = float(os.environ.get("SWING_MATRIX_REFRESH_TTL", "600"))\n',
    '_SWING_MATRIX_REFRESH_TTL = float(os.environ.get("SWING_MATRIX_REFRESH_TTL", "60"))\nSWING_EXECUTION_POLICY = os.environ.get("SWING_EXECUTION_POLICY", "AUTO_PAPER").upper().strip()\n',
    'swing freshness',
)
anchor = '''def _size_new_swing_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:\n    """Size each new name against full slot capacity so later fills do not resize."""\n    return [\n        attach_exit_plan(_size_swing_row(r, sleeve=SWING_CAPITAL, slots=SWING_MATRIX_LOCK_COUNT))\n        for r in rows[:SWING_MATRIX_LOCK_COUNT]\n    ]\n\n\n'''
helpers = '''def _paper_execute_swing_row(row: dict[str, Any], *, filled_at: str | None = None) -> dict[str, Any]:\n    """Record an automatic PAPER fill after deterministic gates; never place a broker order."""\n    if SWING_EXECUTION_POLICY != "AUTO_PAPER":\n        return row\n    qty = int(row.get("approxQty") or 0)\n    entry = _f(row.get("entryPrice")) or 0.0\n    if qty <= 0 or entry <= 0:\n        return row\n    at = filled_at or _utc_now_iso()\n    out = dict(row)\n    lineage = dict(out.get("lineage") or {})\n    fills = list(lineage.get("executedFills") or [])\n    if not fills:\n        fills.append({"side": "BUY", "qty": qty, "price": entry, "filledAt": at, "mode": "PAPER", "source": "SWING_DETERMINISTIC_GATE"})\n    lineage["executedFills"] = fills\n    lineage["triggeredAt"] = lineage.get("triggeredAt") or at\n    out.update({\n        "executionStatus": "FILLED",\n        "executionBasis": "AUTO_PAPER_AFTER_DETERMINISTIC_GATES",\n        "executionMode": "PAPER",\n        "triggered": True,\n        "triggeredAt": out.get("triggeredAt") or at,\n        "qty": qty,\n        "lineage": lineage,\n    })\n    return out\n\n\ndef _paper_execute_swing_rows(rows: list[dict[str, Any]], *, filled_at: str | None = None) -> list[dict[str, Any]]:\n    return [_paper_execute_swing_row(row, filled_at=filled_at) for row in rows]\n\n\n'''
text = replace_once(text, anchor, anchor + helpers, 'paper helpers')
text = replace_once(
    text,
    '    for row in _size_new_swing_rows(new_rows):\n',
    '    for row in _paper_execute_swing_rows(_size_new_swing_rows(new_rows), filled_at=committed_at):\n',
    'paper fill remaining slots',
)
text = replace_once(
    text,
    '        sized = _size_new_swing_rows(long_rows)\n',
    '        sized = _paper_execute_swing_rows(_size_new_swing_rows(long_rows), filled_at=committed_at)\n',
    'paper fill initial lock',
)
text = text.replace('"executionPolicy": "MANUAL_ONLY",', '"executionPolicy": SWING_EXECUTION_POLICY,')
text = text.replace('sess.get("executionPolicy") or "MANUAL_ONLY"', 'sess.get("executionPolicy") or SWING_EXECUTION_POLICY')
p.write_text(text, encoding='utf-8')

# Focused tests.
p = Path('backend/tests/test_swing_automation.py')
text = p.read_text(encoding='utf-8')
text += '''\n\ndef test_auto_paper_execution_records_fill(monkeypatch):\n    monkeypatch.setattr(swing_session, "SWING_EXECUTION_POLICY", "AUTO_PAPER")\n    normalized = swing_session._normalize_swing_row(_raw_buy_pick("PAPER1"), "2026-08-13")\n    assert normalized is not None\n    row = swing_session._size_new_swing_rows([normalized])[0]\n    filled = swing_session._paper_execute_swing_row(row, filled_at="2026-08-13T05:00:00+00:00")\n    assert filled["executionStatus"] == "FILLED"\n    assert filled["executionMode"] == "PAPER"\n    assert filled["triggered"] is True\n    assert filled["qty"] == filled["approxQty"]\n    assert filled["lineage"]["executedFills"][0]["mode"] == "PAPER"\n\n\ndef test_swing_refresh_ttl_defaults_to_one_minute():\n    assert swing_session._SWING_MATRIX_REFRESH_TTL <= 60\n'''
p.write_text(text, encoding='utf-8')

# Static safety assertions ensure the scoped Angel-first wiring exists.
p = Path('backend/tests/test_swing_angel_first_contract.py')
p.write_text('''from pathlib import Path\n\n\ndef test_swing_refresh_is_angel_first_and_nifty500_scoped():\n    src = Path("app/services/angel_one_feed.py").read_text(encoding="utf-8")\n    assert 'swing_hunt = reason == "swing_entry_hunt"' in src\n    assert 'pool = NIFTY_500_LABEL if swing_hunt' in src\n    assert 'angel_first_quotes=swing_hunt' in src\n    assert 'pricePriority": "ANGEL_FIRST_SWING_HUNT"' in src\n\n\ndef test_global_quote_failover_default_is_unchanged():\n    src = Path("app/services/market_data_provider.py").read_text(encoding="utf-8")\n    assert 'NSE primary, Dhan missing-symbol fallback, then Angel final fallback' in src\n''', encoding='utf-8')

print('Swing hunt v2 patch applied')

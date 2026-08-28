from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)

# 1) Add Angel-first quote mode without changing the default market-data behavior.
p = Path('backend/app/services/market_data_provider.py')
text = p.read_text(encoding='utf-8')
text = replace_once(
    text,
    '''def fetch_quotes_with_failover(\n    symbols: Iterable[str],\n    angel_fetch: Callable[[list[str]], dict[str, dict[str, Any]]],\n) -> tuple[dict[str, dict[str, Any]], QuoteCoverage]:\n    """NSE primary, Dhan missing-symbol fallback, then Angel final fallback."""\n    ordered = list(dict.fromkeys(_norm(s) for s in symbols if _norm(s)))\n    quotes: dict[str, dict[str, Any]] = {}\n    providers = {"nse": 0, "dhan": 0, "angel": 0}\n    try:\n        quotes.update(fetch_nse500_quotes(ordered))\n        providers["nse"] = len(quotes)\n    except Exception as exc:\n        log.warning("NSE Nifty 500 quote fetch failed; using Dhan fallback: %s", exc)\n\n    missing = [symbol for symbol in ordered if symbol not in quotes]\n''',
    '''def fetch_quotes_with_failover(\n    symbols: Iterable[str],\n    angel_fetch: Callable[[list[str]], dict[str, dict[str, Any]]],\n    *,\n    angel_first: bool = False,\n) -> tuple[dict[str, dict[str, Any]], QuoteCoverage]:\n    """Bulk quote coverage with an optional Angel-first mode for Swing hunting.\n\n    Default behavior remains NSE -> Dhan -> Angel. ``angel_first=True`` is used\n    only by the Swing entry-hunt refresh so all available Nifty 500 prices come\n    from Angel One first; NSE/Dhan fill only symbols Angel did not return.\n    """\n    ordered = list(dict.fromkeys(_norm(s) for s in symbols if _norm(s)))\n    quotes: dict[str, dict[str, Any]] = {}\n    providers = {"nse": 0, "dhan": 0, "angel": 0}\n\n    if angel_first:\n        try:\n            angel = angel_fetch(ordered)\n            for symbol, quote in angel.items():\n                if symbol in ordered and isinstance(quote, dict):\n                    row = dict(quote)\n                    row["quoteProvider"] = "angel"\n                    quotes[symbol] = row\n                    providers["angel"] += 1\n        except Exception as exc:\n            log.warning("Angel-first Nifty 500 quote fetch failed; filling from NSE/Dhan: %s", exc)\n\n    missing = [symbol for symbol in ordered if symbol not in quotes]\n    if missing:\n        try:\n            nse = fetch_nse500_quotes(missing)\n            for symbol, quote in nse.items():\n                if symbol not in quotes and isinstance(quote, dict):\n                    quotes[symbol] = quote\n                    providers["nse"] += 1\n        except Exception as exc:\n            log.warning("NSE Nifty 500 quote fetch failed; using Dhan fallback: %s", exc)\n\n    missing = [symbol for symbol in ordered if symbol not in quotes]\n''',
    'market_data_provider angel-first block',
)
p.write_text(text, encoding='utf-8')

# 2) Thread Angel-first mode through the live payload only for swing_entry_hunt.
p = Path('backend/app/services/angel_one_feed.py')
text = p.read_text(encoding='utf-8')
text = replace_once(
    text,
    'def run_scheduled_live_refresh(*, reason: str = "scheduled_live_refresh") -> dict[str, Any]:\n    """Live Angel/Yahoo/RSS refresh with LLM day-lock reuse (no force LLM)."""\n    log = logging.getLogger(__name__)\n    pool = (os.getenv("MARKET_PREWORK_POOL") or NIFTY_500_LABEL).strip() or NIFTY_500_LABEL\n',
    'def run_scheduled_live_refresh(*, reason: str = "scheduled_live_refresh") -> dict[str, Any]:\n    """Live quote/candle refresh with LLM day-lock reuse (no force LLM)."""\n    log = logging.getLogger(__name__)\n    swing_hunt = reason == "swing_entry_hunt"\n    pool = NIFTY_500_LABEL if swing_hunt else ((os.getenv("MARKET_PREWORK_POOL") or NIFTY_500_LABEL).strip() or NIFTY_500_LABEL)\n',
    'scheduled refresh swing pool',
)
text = replace_once(
    text,
    '            force_llm_refresh=False,\n        )\n',
    '            force_llm_refresh=False,\n            angel_first_quotes=swing_hunt,\n        )\n',
    'scheduled refresh pass angel flag',
)
text = replace_once(
    text,
    'def _build_payload_from_live_data(\n    client: AngelOneClient,\n    pool_name: str | None = None,\n    custom_prompt: str | None = None,\n    force_llm_refresh: bool = False,\n    prior_snapshot: dict[str, Any] | None = None,\n    on_progress: Callable[[str], None] | None = None,\n) -> dict[str, Any]:\n',
    'def _build_payload_from_live_data(\n    client: AngelOneClient,\n    pool_name: str | None = None,\n    custom_prompt: str | None = None,\n    force_llm_refresh: bool = False,\n    prior_snapshot: dict[str, Any] | None = None,\n    on_progress: Callable[[str], None] | None = None,\n    angel_first_quotes: bool = False,\n) -> dict[str, Any]:\n',
    'live payload signature',
)
text = replace_once(
    text,
    '    stock_quotes_raw, quote_coverage = _fetch_stock_quotes_with_coverage(client, stock_universe)\n',
    '    stock_quotes_raw, quote_coverage = _fetch_stock_quotes_with_coverage(\n        client, stock_universe, angel_first=angel_first_quotes\n    )\n',
    'live payload quote mode',
)
text = replace_once(
    text,
    'def build_market_payload(\n    client: AngelOneClient,\n    pool_name: str | None = None,\n    force_refresh: bool = False,\n    custom_prompt: str | None = None,\n    allow_fallback: bool = True, # If live fetch fails, allow falling back to snapshot\n    prefer_cache: bool = False, # If true, try cache first, then live if cache is empty/stale\n    force_llm_refresh: bool = False,  # When false, reuse day-locked / TTL-fresh snapshot AI\n    on_progress: Callable[[str], None] | None = None,\n) -> dict[str, Any]:\n',
    'def build_market_payload(\n    client: AngelOneClient,\n    pool_name: str | None = None,\n    force_refresh: bool = False,\n    custom_prompt: str | None = None,\n    allow_fallback: bool = True, # If live fetch fails, allow falling back to snapshot\n    prefer_cache: bool = False, # If true, try cache first, then live if cache is empty/stale\n    force_llm_refresh: bool = False,  # When false, reuse day-locked / TTL-fresh snapshot AI\n    on_progress: Callable[[str], None] | None = None,\n    angel_first_quotes: bool = False,\n) -> dict[str, Any]:\n',
    'build_market_payload signature',
)
text = replace_once(
    text,
    '            prior_snapshot=snapshot,\n            on_progress=on_progress,\n        )\n',
    '            prior_snapshot=snapshot,\n            on_progress=on_progress,\n            angel_first_quotes=angel_first_quotes,\n        )\n',
    'build payload pass angel flag',
)
# Patch helper signature/call; tolerate exact existing formatting.
old = 'def _fetch_stock_quotes_with_coverage(\n    client: AngelOneClient, instruments: list[Instrument]\n) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:'
if old not in text:
    old = 'def _fetch_stock_quotes_with_coverage(\n    client: AngelOneClient,\n    instruments: list[Instrument],\n) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:'
new = old.replace(') -> tuple', '    *,\n    angel_first: bool = False,\n) -> tuple')
text = replace_once(text, old, new, 'quote helper signature')
needle = '    quotes, coverage = fetch_quotes_with_failover(symbols, _angel_fetch)\n'
text = replace_once(
    text,
    needle,
    '    quotes, coverage = fetch_quotes_with_failover(symbols, _angel_fetch, angel_first=angel_first)\n',
    'quote helper call',
)
p.write_text(text, encoding='utf-8')

# 3) Swing: 60-second quote freshness + automatic PAPER fills after every gate passes.
p = Path('backend/app/services/swing_session.py')
text = p.read_text(encoding='utf-8')
text = replace_once(
    text,
    '_SWING_MATRIX_REFRESH_TTL = float(os.environ.get("SWING_MATRIX_REFRESH_TTL", "600"))\n',
    '_SWING_MATRIX_REFRESH_TTL = float(os.environ.get("SWING_MATRIX_REFRESH_TTL", "60"))\nSWING_EXECUTION_POLICY = os.environ.get("SWING_EXECUTION_POLICY", "AUTO_PAPER").upper().strip()\n',
    'swing refresh ttl',
)
insert_after = '''def _size_new_swing_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:\n    """Size each new name against full slot capacity so later fills do not resize."""\n    return [\n        attach_exit_plan(_size_swing_row(r, sleeve=SWING_CAPITAL, slots=SWING_MATRIX_LOCK_COUNT))\n        for r in rows[:SWING_MATRIX_LOCK_COUNT]\n    ]\n\n\n'''
addition = '''def _paper_execute_swing_row(row: dict[str, Any], *, filled_at: str | None = None) -> dict[str, Any]:\n    """Record a deterministic paper fill; never sends an order to Angel One."""\n    if SWING_EXECUTION_POLICY != "AUTO_PAPER":\n        return row\n    qty = int(row.get("approxQty") or 0)\n    entry = _f(row.get("entryPrice")) or 0.0\n    if qty <= 0 or entry <= 0:\n        return row\n    at = filled_at or _utc_now_iso()\n    out = dict(row)\n    lineage = dict(out.get("lineage") or {})\n    fills = list(lineage.get("executedFills") or [])\n    if not fills:\n        fills.append({\n            "side": "BUY",\n            "qty": qty,\n            "price": entry,\n            "filledAt": at,\n            "mode": "PAPER",\n            "source": "SWING_DETERMINISTIC_GATE",\n        })\n    lineage["executedFills"] = fills\n    lineage["triggeredAt"] = lineage.get("triggeredAt") or at\n    out.update({\n        "executionStatus": "FILLED",\n        "executionBasis": "AUTO_PAPER_AFTER_DETERMINISTIC_GATES",\n        "executionMode": "PAPER",\n        "triggered": True,\n        "triggeredAt": out.get("triggeredAt") or at,\n        "qty": qty,\n        "lineage": lineage,\n    })\n    return out\n\n\ndef _paper_execute_swing_rows(rows: list[dict[str, Any]], *, filled_at: str | None = None) -> list[dict[str, Any]]:\n    return [_paper_execute_swing_row(row, filled_at=filled_at) for row in rows]\n\n\n'''
text = replace_once(text, insert_after, insert_after + addition, 'paper execution helpers')
text = replace_once(
    text,
    '    for row in _size_new_swing_rows(new_rows):\n',
    '    for row in _paper_execute_swing_rows(_size_new_swing_rows(new_rows), filled_at=committed_at):\n',
    'paper fill appended rows',
)
text = replace_once(
    text,
    '        sized = _size_new_swing_rows(long_rows)\n',
    '        sized = _paper_execute_swing_rows(_size_new_swing_rows(long_rows), filled_at=committed_at)\n',
    'paper fill initial rows',
)
text = text.replace('"executionPolicy": "MANUAL_ONLY",', '"executionPolicy": SWING_EXECUTION_POLICY,')
text = text.replace('sess.get("executionPolicy") or "MANUAL_ONLY"', 'sess.get("executionPolicy") or SWING_EXECUTION_POLICY')
p.write_text(text, encoding='utf-8')

# 4) Tests: Angel-first priority and automatic paper fill.
p = Path('backend/tests/test_market_data_provider.py')
text = p.read_text(encoding='utf-8')
text += '''\n\ndef test_angel_first_quotes_prefer_angel(monkeypatch):\n    from app.services import market_data_provider as mdp\n\n    monkeypatch.setattr(mdp, "fetch_nse500_quotes", lambda symbols: {s: {"ltp": 90.0, "quoteProvider": "nse"} for s in symbols})\n    monkeypatch.setattr(mdp, "fetch_dhan_bulk_quotes", lambda symbols: {})\n\n    def angel(symbols):\n        return {s: {"ltp": 100.0} for s in symbols}\n\n    quotes, coverage = mdp.fetch_quotes_with_failover(["AAA", "BBB"], angel, angel_first=True)\n    assert quotes["AAA"]["ltp"] == 100.0\n    assert quotes["AAA"]["quoteProvider"] == "angel"\n    assert coverage.providers["angel"] == 2\n    assert coverage.providers["nse"] == 0\n    assert coverage.selection_allowed is True\n'''
p.write_text(text, encoding='utf-8')

p = Path('backend/tests/test_swing_automation.py')
text = p.read_text(encoding='utf-8')
text += '''\n\ndef test_auto_paper_execution_records_fill(monkeypatch):\n    monkeypatch.setattr(swing_session, "SWING_EXECUTION_POLICY", "AUTO_PAPER")\n    row = swing_session._size_new_swing_rows([swing_session._normalize_swing_row(_raw_buy_pick("PAPER1"), "2026-08-13")])[0]\n    filled = swing_session._paper_execute_swing_row(row, filled_at="2026-08-13T05:00:00+00:00")\n    assert filled["executionStatus"] == "FILLED"\n    assert filled["executionMode"] == "PAPER"\n    assert filled["triggered"] is True\n    assert filled["qty"] == filled["approxQty"]\n    assert filled["lineage"]["executedFills"][0]["mode"] == "PAPER"\n\n\ndef test_swing_refresh_ttl_defaults_to_one_minute():\n    assert swing_session._SWING_MATRIX_REFRESH_TTL <= 60\n'''
p.write_text(text, encoding='utf-8')

print('Swing hunt pipeline patch applied')

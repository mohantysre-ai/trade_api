from pathlib import Path

PATH = Path("backend/app/services/ai_ticker_news.py")
text = PATH.read_text(encoding="utf-8")

# 1) Broaden Google News RSS queries while retaining the same recency window.
old_queries = '''    queries = [
        f'(\"{company}\" OR \"{ticker}\" NSE) stock when:{NEWS_LOOKBACK_DAYS}d',
        (
            f'\"{alias}\" (site:moneycontrol.com OR site:economictimes.indiatimes.com '
            f'OR site:livemint.com OR site:business-standard.com '
            f'OR site:financialexpress.com OR site:cnbctv18.com OR site:reuters.com) '
            f'when:{NEWS_LOOKBACK_DAYS}d'
        ),
    ]
'''
new_queries = '''    queries = [
        f'(\"{company}\" OR \"{ticker}\" NSE) stock when:{NEWS_LOOKBACK_DAYS}d',
        (
            f'\"{alias}\" (site:moneycontrol.com OR site:economictimes.indiatimes.com '
            f'OR site:livemint.com OR site:business-standard.com '
            f'OR site:financialexpress.com OR site:cnbctv18.com OR site:reuters.com) '
            f'when:{NEWS_LOOKBACK_DAYS}d'
        ),
        # Simple fallbacks are intentionally less clever. Google News RSS can
        # return zero results for heavily-parenthesized queries even when there
        # is obvious recent coverage for a liquid NSE ticker.
        f'\"{company}\" when:{NEWS_LOOKBACK_DAYS}d',
        f'{ticker} NSE when:{NEWS_LOOKBACK_DAYS}d',
    ]
'''
if old_queries not in text:
    raise SystemExit("Google News query block not found")
text = text.replace(old_queries, new_queries, 1)

# 2) Enforce that report-level narrative cannot outlive its source evidence.
anchor = '''def _evidence_status(bundle: NewsScrapeBundle) -> str:\n'''
helper = '''def _enforce_evidence_contract(\n    summary: dict,\n    articles: list[TickerNewsArticle],\n    evidence_status: str,\n    ticker: str,\n) -> dict:\n    \"\"\"Prevent a substantive ticker-news narrative from existing without headlines.\n\n    Verified article evidence is deterministic and authoritative. If the current\n    scrape has no accepted article, stale/cache/LLM narrative fields must not be\n    presented as current ticker intelligence.\n    \"\"\"\n    if articles:\n        return dict(summary)\n\n    cleaned = dict(summary)\n    for key in (\n        \"insider_activity\",\n        \"institutional_activity\",\n        \"order_book_block_deals\",\n        \"future_expansion_capex\",\n        \"auditor_changes\",\n        \"dividend_news\",\n        \"new_orders_contracts\",\n        \"earnings_results\",\n        \"management_changes\",\n        \"regulatory_filings\",\n        \"risk_flags\",\n    ):\n        cleaned[key] = \"\"\n    cleaned[\"sentiment_overall\"] = \"Neutral\"\n    if str(evidence_status).upper() == \"SOURCE_UNAVAILABLE\":\n        cleaned[\"summary_headline\"] = f\"No verified recent headline for {ticker} — news sources unavailable\"\n    else:\n        cleaned[\"summary_headline\"] = f\"No verified recent headline found for {ticker} in the last {NEWS_LOOKBACK_DAYS} days\"\n    cleaned[\"llmUsed\"] = False\n    cleaned[\"digestMode\"] = \"no-evidence\"\n    return cleaned\n\n\n'''
if anchor not in text:
    raise SystemExit("evidence status anchor not found")
text = text.replace(anchor, helper + anchor, 1)

old_merge = '''    llm_result = _merge_deterministic_news_evidence(llm_result, articles)\n\n    # Step 3: Build report\n'''
new_merge = '''    llm_result = _merge_deterministic_news_evidence(llm_result, articles)\n    llm_result = _enforce_evidence_contract(llm_result, articles, evidence_status, ticker)\n\n    # Step 3: Build report\n'''
if old_merge not in text:
    raise SystemExit("final evidence merge anchor not found")
text = text.replace(old_merge, new_merge, 1)

PATH.write_text(text, encoding="utf-8")
print("Broadened ticker-news discovery and enforced headline evidence contract")

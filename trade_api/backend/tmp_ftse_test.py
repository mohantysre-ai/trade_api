from global_feed import YahooInstrument, _fetch_yahoo_html_quote, _fetch_yahoo_api_quote, _fmt_index

inst = YahooInstrument('ftse', '^FTSE', 'FTSE 100', 'index', _fmt_index)
print('html fallback:', _fetch_yahoo_html_quote(inst))
print('api fallback:', _fetch_yahoo_api_quote(inst))

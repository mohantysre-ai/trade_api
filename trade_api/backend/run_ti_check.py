from angel_one_feed import _llm_select_and_analyze_stocks, _load_last_snapshot
import json
s=_load_last_snapshot()
sel,ti = _llm_select_and_analyze_stocks(s.get('stocks',[]), s.get('macroDataStrip',{}), s.get('news',[]))
print('selected_count=', len(sel))
print('ti_present=', ti is not None)
if ti is not None:
    print(list(ti.keys())[:10])
    print(json.dumps(ti)[:1000])

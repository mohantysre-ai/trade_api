import requests
import re
url = 'https://www.moneycontrol.com/india/stockpricequote/indian-index/indices/GIFTNIFTY'
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Referer': 'https://www.moneycontrol.com/'
}
r = requests.get(url, headers=headers, timeout=10)
text = r.text
print('final', r.url)
print('status', r.status_code)
print('contains GIFTNIFTY', 'GIFTNIFTY' in text)
print('contains priceapi', 'priceapi.moneycontrol.com' in text)
for m in re.finditer(r'(https://priceapi\.moneycontrol\.com[^"\s]+)', text):
    print('endpoint', m.group(1))
# search for scId and dataFeedDomain
for keyword in ['dataFeedDomain', 'scdid', 'stock?scId', 'symbol', 'GIFTNIFTY']:
    idx = text.find(keyword)
    print(keyword, idx)
    if idx != -1:
        snippet = text[max(0, idx-120):idx+120]
        print(snippet)

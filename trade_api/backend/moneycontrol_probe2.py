import requests
urls=[
    'https://priceapi.moneycontrol.com/techCharts/indianMarket/stock?scId=GIFTNIFTY',
    'https://priceapi.moneycontrol.com/techCharts/indianMarket/stock?scId=GIFTNIFTY&scid=GIFTNIFTY',
    'https://priceapi.moneycontrol.com/techCharts/indianMarket/stock?scId=GIFTNIFTY&stkname=indices',
    'https://priceapi.moneycontrol.com/techCharts/indianMarket/stock?scId=GIFTNIFTY&series=1',
    'https://priceapi.moneycontrol.com/techCharts/indianMarket/stock?scId=GIFTNIFTY&series=1&stkname=indices'
]
headers={
    'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept':'application/json, text/javascript, */*; q=0.01',
    'Referer':'https://www.moneycontrol.com/'
}
for url in urls:
    try:
        r=requests.get(url, headers=headers, timeout=10)
        print('URL', url, 'status', r.status_code)
        print(r.text[:1000])
    except Exception as e:
        print('ERR', url, e)

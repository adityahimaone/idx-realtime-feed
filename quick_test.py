import httpx, json

token=open('.env').read().split('STOCKBIT_BEARER_TOKEN=')[1].splitlines()[0].strip()
print(f'Token: {token[:20]}...{token[-10:]}')

# Test price-feed
url='https://exodus.stockbit.com/company-price-feed/v2/orderbook/companies/ADRO'
print('=== price-feed ADRO ===')
try:
    r=httpx.get(url, headers={'Authorization': f'Bearer {token}'}, timeout=10)
    print(f'Status: {r.status_code}')
    if r.status_code==200:
        d=r.json()
        print(json.dumps(d, indent=2)[:800])
    else:
        print(r.text[:300])
except Exception as e:
    print(f'Error: {e}')

# Test watchlist
wl='https://exodus.stockbit.com/watchlist/2624360?page=1&limit=100&setfincol=1'
print('\n=== watchlist ===')
try:
    r=httpx.get(wl, headers={'Authorization': f'Bearer {token}'}, timeout=10)
    print(f'Status: {r.status_code}')
    if r.status_code==200:
        d=r.json()
        subs=[x['symbol'] for x in d['data']['result']]
        print(f'Symbols ({len(subs)}): {subs}')
        print(json.dumps(d['data']['result'][0], indent=2)[:500])
    else:
        print(r.text[:300])
except Exception as e:
    print(f'Error: {e}')

"""fleet_health_check.py
Pantau kesehatan seluruh akun TokenHarbor di 9Router.
- Load semua key dari provider 'TH' (openai-compatible-chat-07ede055-d26a-4690-9e3b-b1930b247502)
- Test 2 model gratis: deepseek-v4-flash:free & mimo-v2.5:free
- Output: status json + ringkasan untuk notifikasi
"""
import sqlite3, json, requests, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

DB = r'C:\Users\TUF Gaming A15\AppData\Roaming\9router\db\data.sqlite'
PROVIDER = 'openai-compatible-chat-07ede055-d26a-4690-9e3b-b1930b247502'
MODELS = ['deepseek-v4-flash:free', 'mimo-v2.5:free']
URL = 'https://tokenharbor.ai/v1/chat/completions'
TIMEOUT = 30
MAX_WORKERS = 8  # parallel

def load_keys():
    conn = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
    rows = conn.execute("SELECT name, email, data FROM providerConnections WHERE provider=?", (PROVIDER,)).fetchall()
    out = []
    for name, email, data in rows:
        try:
            d = json.loads(data)
            key = d.get('apiKey')
            if key:
                out.append({'name': name, 'email': email, 'key': key})
        except Exception:
            pass
    conn.close()
    return out

def test_key(entry, model):
    try:
        r = requests.post(
            URL,
            headers={'Authorization': f'Bearer {entry["key"]}', 'Content-Type': 'application/json'},
            json={'model': model, 'messages': [{'role': 'user', 'content': 'ping'}], 'max_tokens': 8, 'stream': False},
            timeout=TIMEOUT
        )
        return r.status_code, model, entry['name']
    except Exception as e:
        return -1, model, f'{entry["name"]} (err: {str(e)[:30]})'

def main():
    keys = load_keys()
    if not keys:
        print("ERROR: no keys found")
        sys.exit(1)
    
    print(f'[{datetime.now().isoformat()}] Testing {len(keys)} keys × {len(MODELS)} models...')
    
    tasks = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        for entry in keys:
            for model in MODELS:
                tasks.append(ex.submit(test_key, entry, model))
        
        results = {'ok': [], 'fail': []}
        for fut in as_completed(tasks):
            status, model, name = fut.result()
            if status == 200:
                results['ok'].append((name, model))
            else:
                results['fail'].append((name, model, status))
    
    total = len(tasks)
    ok_n = len(results['ok'])
    fail_n = len(results['fail'])
    
    print(f'\n=== HEALTH CHECK RESULT ===')
    print(f'Total tests:    {total}')
    print(f'Success:        {ok_n} ({ok_n/total*100:.1f}%)')
    print(f'Failed:         {fail_n} ({fail_n/total*100:.1f}%)')
    print(f'Distinct keys:  {len(keys)}')
    print(f'Active keys:    {len(keys) - len(set(f[0] for f in results["fail"]))}/{len(keys)}')
    
    if fail_n:
        print(f'\n=== FAILED ACCOUNTS ===')
        by_key = {}
        for name, model, status in results['fail']:
            by_key.setdefault(name, []).append((model, status))
        for name, fails in by_key.items():
            print(f'  {name}: {fails}')
        sys.exit(2)  # non-zero exit so cron notifies
    else:
        print(f'\nAll {total} tests passed.')
        sys.exit(0)

if __name__ == '__main__':
    main()

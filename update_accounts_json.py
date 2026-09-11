"""update_accounts_json.py — Retest all 20 active accounts, update their test records for 2-model reality,
and rewrite accounts.json cleanly.
"""
import json, requests, concurrent.futures

ACCOUNTS = "D:/tokenharbor-farmer/accounts.json"
MODELS = ["deepseek-v4-flash:free", "mimo-v2.5:free"]
BASE_URL = "https://tokenharbor.ai/v1/chat/completions"

def test_model(key, model):
    try:
        r = requests.post(
            BASE_URL,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={"model": model, "messages": [{"role": "user", "content": "say ok"}],
                  "max_tokens": 5, "stream": False},
            timeout=15
        )
        if r.status_code == 200:
            c = r.json().get("choices", [{}])[0].get("message", {}).get("content", "")
            return True, c.strip()[:20]
        return False, f"HTTP {r.status_code}"
    except Exception as e:
        return False, str(e)[:30]

def process_acc(acc):
    key = acc.get("api_key") or ""
    if not key.startswith("thk_live"):
        return acc, False
    
    tests = {}
    all_ok = True
    for m in MODELS:
        ok, msg = test_model(key, m)
        tests[m] = ok
        if ok:
            tests[m + "_content"] = msg
        else:
            all_ok = False
            
    acc["verified"] = True
    acc["free_enabled"] = True
    acc["tests"] = tests
    acc["ok"] = all_ok
    return acc, all_ok

# Load unique
seen = {}
for line in open(ACCOUNTS, encoding="utf-8"):
    line = line.strip()
    if not line: continue
    try:
        a = json.loads(line)
        e = a.get("email")
        if e: seen[e] = a
    except: pass

acc_list = list(seen.values())
print(f"Loaded {len(acc_list)} unique accounts. Verifying via API...")

updated_list = []
fully_ok_count = 0

with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
    results = list(ex.map(process_acc, acc_list))

for acc, ok in results:
    if ok:
        fully_ok_count += 1
    updated_list.append(acc)

# Save backup then overwrite
import shutil
shutil.copyfile(ACCOUNTS, ACCOUNTS + ".bak")

with open(ACCOUNTS, "w", encoding="utf-8") as f:
    for acc in updated_list:
        f.write(json.dumps(acc) + "\n")

print(f"=== UPDATE COMPLETE ===")
print(f"• Total accounts in file: {len(updated_list)}")
print(f"• FULL-OK (deepseek + mimo): {fully_ok_count} / {len(updated_list)}")
print(f"• Backup saved to: {ACCOUNTS}.bak")

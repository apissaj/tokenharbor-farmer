"""gen_fleet_csv.py — Generate fleet_success.csv from REAL accounts.json + live test."""
import json, requests, concurrent.futures

ACCOUNTS = "D:/tokenharbor-farmer/accounts.json"
MODELS = ["deepseek-v4-flash:free", "mimo-v2.5:free"]
BASE_URL = "https://tokenharbor.ai/v1/chat/completions"

def load_accounts():
    seen = {}
    for line in open(ACCOUNTS, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            a = json.loads(line)
            e = a.get("email")
            if e:
                seen[e] = a
        except Exception:
            pass
    return list(seen.values())

def test_model(key, model):
    try:
        r = requests.post(BASE_URL,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={"model": model, "messages": [{"role": "user", "content": "say ok"}],
                  "max_tokens": 5, "stream": False},
            timeout=15)
        if r.status_code == 200:
            c = r.json().get("choices", [{}])[0].get("message", {}).get("content", "")
            return True, c.strip()[:15]
        return False, f"HTTP {r.status_code}"
    except Exception as e:
        return False, str(e)[:25]

def test_account(acc):
    email = acc.get("email", "?")
    key = acc.get("api_key") or ""
    if not key.startswith("thk_live"):
        return email, None, None, f"no_valid_key({key[:12]})"
    r1 = test_model(key, MODELS[0])
    r2 = test_model(key, MODELS[1])
    return email, r1, r2, None

accs = load_accounts()
print(f"Total unique accounts: {len(accs)}")
rows, nokey = [], 0
with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
    for email, r1, r2, err in ex.map(test_account, accs):
        if err:
            nokey += 1
            print(f"[SKIP] {email:40s} {err}")
            continue
        ds_ok, ds_msg = r1
        mi_ok, mi_msg = r2
        status = "FULL" if (ds_ok and mi_ok) else ("PARTIAL" if (ds_ok or mi_ok) else "DEAD")
        print(f"[{status:7s}] {email:40s} ds={'OK' if ds_ok else ds_msg} mimo={'OK' if mi_ok else mi_msg}")
        rows.append((email, status, ds_ok, mi_ok))

with open("D:/tokenharbor-farmer/fleet_success.csv", "w", encoding="utf-8") as f:
    f.write("email,status,deepseek_ok,mimo_ok\n")
    for email, status, ds, mi in rows:
        f.write(f"{email},{status},{str(ds).lower()},{str(mi).lower()}\n")

full = sum(1 for r in rows if r[1] == "FULL")
partial = sum(1 for r in rows if r[1] == "PARTIAL")
dead = sum(1 for r in rows if r[1] == "DEAD")
print("=" * 60)
print(f"FULL: {full} | PARTIAL: {partial} | DEAD: {dead} | NO-KEY: {nokey}")
print("CSV -> D:/tokenharbor-farmer/fleet_success.csv")

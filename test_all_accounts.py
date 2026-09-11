"""test_all_accounts.py — Fast parallel verification for ALL TokenHarbor accounts.
Tests every account in accounts.json for deepseek-v4-flash:free, mimo-v2.5:free, and qwen3.8-27b:free.
"""
import sys, json, os, time
import concurrent.futures
import requests

ACCOUNTS = "D:/tokenharbor-farmer/accounts.json"
MODELS = ["deepseek-v4-flash:free", "mimo-v2.5:free"]  # TokenHarbor 2026-09: qwen3.8-27b:free dihapus
BASE_URL = "https://tokenharbor.ai/v1/chat/completions"

def test_single_model(key, model):
    try:
        r = requests.post(
            BASE_URL,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json"
            },
            json={
                "model": model,
                "messages": [{"role": "user", "content": "say ok"}],
                "max_tokens": 5,
                "stream": False
            },
            timeout=12
        )
        if r.status_code == 200:
            data = r.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            return True, content.strip()[:20]
        else:
            return False, f"HTTP {r.status_code}"
    except Exception as e:
        return False, str(e)[:30]

def test_account(idx, acc):
    email = acc.get("email", "unknown")
    key = acc.get("api_key", "")
    if not key or not key.startswith("thk_live"):
        return {
            "idx": idx,
            "email": email,
            "key_valid": False,
            "results": {m: (False, "no_key") for m in MODELS},
            "all_ok": False
        }
    
    res = {}
    all_ok = True
    for m in MODELS:
        ok, msg = test_single_model(key, m)
        res[m] = (ok, msg)
        if not ok:
            all_ok = False
            
    return {
        "idx": idx,
        "email": email,
        "key_valid": True,
        "results": res,
        "all_ok": all_ok
    }

def main():
    if not os.path.exists(ACCOUNTS):
        print(f"File not found: {ACCOUNTS}")
        return

    raw_accs = []
    with open(ACCOUNTS, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                raw_accs.append(json.loads(line))
            except Exception:
                pass

    # Deduplicate by email
    seen = {}
    for a in raw_accs:
        e = a.get("email")
        if e:
            seen[e] = a
    acc_list = list(seen.values())

    print(f"=== TESTING TOKENHARBOR FLEET ({len(acc_list)} ACCOUNTS) ===")
    print(f"Models: {', '.join(MODELS)}")
    print("-" * 75)

    stats = {m: 0 for m in MODELS}
    fully_functional = 0
    tested_count = 0

    # Parallelize across accounts
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(test_account, i+1, acc): acc for i, acc in enumerate(acc_list)}
        
        for future in concurrent.futures.as_completed(futures):
            res = future.result()
            idx = res["idx"]
            email = res["email"]
            prefix = email.split("@")[0] if "@" in email else email
            
            if not res["key_valid"]:
                print(f"[{idx:02d}/{len(acc_list):02d}] ❌ {prefix:20s} | NO VALID API KEY")
                continue

            tested_count += 1
            icons = []
            for m in MODELS:
                ok, msg = res["results"][m]
                if ok:
                    stats[m] += 1
                    icons.append(f"{m.split(':')[0]}: ✓")
                else:
                    icons.append(f"{m.split(':')[0]}: ✗({msg})")

            if res["all_ok"]:
                fully_functional += 1
                status_tag = "✅ ALL OK"
            else:
                status_tag = "⚠️ PARTIAL/FAIL"

            print(f"[{idx:02d}/{len(acc_list):02d}] {status_tag:15s} {prefix:20s} | " + " | ".join(icons))

    print("=" * 75)
    print(f"📊 SUMMARY REPORT:")
    print(f"• Total accounts loaded : {len(acc_list)}")
    print(f"• Accounts tested        : {tested_count}")
    print(f"• 100% Fully Functional  : {fully_functional} / {tested_count}")
    for m in MODELS:
        print(f"• {m:22s} : {stats[m]} / {tested_count} pass ({stats[m]/max(tested_count,1)*100:.1f}%)")

if __name__ == "__main__":
    main()

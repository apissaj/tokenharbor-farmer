"""enable_free_batch.py — For accounts already verified but with free not enabled,
login + enable free models + test 3 models. Reads accounts.json, skips ok ones.
Usage: python enable_free_batch.py
"""
import sys, json, time, uuid, urllib.request, os

sys.path.insert(0, os.path.dirname(__file__))
from pipeline import login_and_enable_free, test_model, log_account

ACCOUNTS = os.path.join(os.path.dirname(__file__), "accounts.json")

def main():
    accs = []
    for line in open(ACCOUNTS):
        line = line.strip()
        if not line:
            continue
        try:
            accs.append(json.loads(line))
        except Exception:
            pass
    print(f"loaded {len(accs)} accounts")
    processed = 0
    for acc in accs:
        email = acc.get("email")
        pw = acc.get("password")
        key = acc.get("api_key")
        if not email or not pw or not key:
            continue
        # skip if already ok
        if acc.get("tests") and all(acc["tests"].get(m) for m in
                                    ["deepseek-v4-flash:free", "mimo-v2.5:free", "qwen3.8-27b:free"]):
            print(f"[skip] {email} already tested")
            continue
        print(f"\n[*] processing {email}")
        tab = login_and_enable_free(email, pw)
        if not tab:
            print(f"[!] login failed for {email}")
            continue
        tests = {}
        for m in ["deepseek-v4-flash:free", "mimo-v2.5:free", "qwen3.8-27b:free"]:
            t = test_model(key, m)
            tests[m] = t.get("ok", False)
            if t.get("ok"):
                tests[m + "_content"] = t.get("content", "")
        acc["verified"] = True
        acc["free_enabled"] = True
        acc["tests"] = tests
        acc["ok"] = all(tests.values())
        # overwrite line: simplest is append new record + mark old
        log_account(acc)
        processed += 1
        print(f"[{'OK' if acc['ok'] else 'FAIL'}] {email} tests={tests}")
    print(f"\n=== processed {processed} accounts ===")


if __name__ == "__main__":
    main()

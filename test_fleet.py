"""test_fleet.py — Verify all accounts in accounts.json can call 3 free models.
Reports success rate + per-model pass count.
Usage: python test_fleet.py
"""
import sys, json, os

sys.path.insert(0, os.path.dirname(__file__))
from pipeline import test_model

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
    # unique by email, keep verified+thk_live
    seen = {}
    for a in accs:
        e = a.get("email")
        if not e:
            continue
        if e not in seen:
            seen[e] = a
    models = ["deepseek-v4-flash:free", "mimo-v2.5:free", "qwen3.8-27b:free"]
    total_ok = 0
    model_pass = {m: 0 for m in models}
    tested = 0
    for a in seen.values():
        key = a.get("api_key") or ""
        if not key.startswith("thk_live"):
            continue
        tested += 1
        allpass = True
        for m in models:
            t = test_model(key, m)
            ok = t.get("ok", False)
            if ok:
                model_pass[m] += 1
            else:
                allpass = False
        if allpass:
            total_ok += 1
        print(f"[{'OK' if allpass else 'FAIL'}] {a['email'].split('@')[0]:18s} " +
              " ".join(f"{m.split(':')[0]}:{'✓' if test_model(key,m).get('ok') else '✗'}" for m in models))
    print(f"\n=== {total_ok}/{tested} accounts fully working ===")
    for m in models:
        print(f"  {m}: {model_pass[m]}/{tested} pass")
    print(f"  Total active routes: {sum(model_pass.values())}")


if __name__ == "__main__":
    main()

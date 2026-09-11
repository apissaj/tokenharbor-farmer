"""pipeline_batch_verify.py — Generate a batch of completions per free model for every FULL‑OK account.
Usage: python pipeline_batch_verify.py [num_per_model]
"""
import json, sys, concurrent.futures, requests, os

ACCOUNTS = "D:/tokenharbor-farmer/accounts.json"
BASE_URL = "https://tokenharbor.ai/v1/chat/completions"
MODELS = ["deepseek-v4-flash:free", "mimo-v2.5:free"]
NUM = int(sys.argv[1]) if len(sys.argv) > 1 else 3  # default 3 prompts per model


def load_full_ok():
    uniq = {}
    for line in open(ACCOUNTS, encoding="utf-8"):
        line = line.strip()
        if not line: continue
        try:
            a = json.loads(line)
            e = a.get("email")
            if e: uniq[e] = a
        except Exception:
            pass
    result = []
    for a in uniq.values():
        t = a.get("tests", {})
        if t.get("deepseek-v4-flash:free") and t.get("mimo-v2.5:free"):
            result.append(a)
    return result

def request_one(key, model, prompt_id):
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": f"generate token #{prompt_id}"}],
        "max_tokens": 15,
        "stream": False
    }
    try:
        r = requests.post(BASE_URL, headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"}, json=payload, timeout=12)
        if r.status_code == 200:
            return r.json().get("choices", [{}])[0].get("message", {}).get("content", "").strip()
        return f"HTTP{r.status_code}"
    except Exception as e:
        return f"ERR:{str(e)[:20]}"

def generate_for_account(acc):
    key = acc["api_key"]
    email = acc["email"]
    out = []
    for m in MODELS:
        for i in range(1, NUM+1):
            txt = request_one(key, m, i)
            out.append({"email": email, "model": m, "prompt_id": i, "result": txt})
    return out

if __name__ == "__main__":
    full_accounts = load_full_ok()
    print(f"Generating batch for {len(full_accounts)} accounts, {NUM} prompts per model ({len(MODELS)} models).")
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        for batch in ex.map(generate_for_account, full_accounts):
            results.extend(batch)
    out_path = os.path.expanduser("~/tokenharbor_batch_results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"✅ Done – {len(results)} results saved to {out_path}")

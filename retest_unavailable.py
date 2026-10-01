"""Re-test providerConnections rows that 9Router market 'unavailable' (502 timeouts).

Serial by design: tokenharbor.ai free-model endpoint rate-limits ~12 req/min per IP,
parallel workers cause fleet-wide 429 false alarms.

Usage: python retest_unavailable.py <export.json> <out.jsonl>
"""
import json
import sys
import time
import urllib.error
import urllib.request

ENDPOINT = "https://tokenharbor.ai/v1/chat/completions"
MODEL = "deepseek-v4-flash:free"
BODY = json.dumps({
    "model": MODEL,
    "messages": [{"role": "user", "content": "ping"}],
    "max_tokens": 4,
}).encode()

SLEEP = 2.0          # steady pace, ~30/min ceiling
RETRY_429_SLEEP = 20


def probe(api_key, timeout=25):
    req = urllib.request.Request(
        ENDPOINT,
        data=BODY,
        headers={
            "Authorization": "Bearer " + api_key,
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read(200).decode("utf-8", "ignore")
    except urllib.error.HTTPError as e:
        return e.code, e.read(200).decode("utf-8", "ignore")
    except Exception as e:  # noqa: BLE001 - any transport failure is a data point
        return 0, f"{type(e).__name__}: {e}"


def main():
    src, dst = sys.argv[1], sys.argv[2]
    rows = json.load(open(src, encoding="utf-8"))
    out = open(dst, "a", encoding="utf-8")
    ok = dead = unknown = 0
    for i, row in enumerate(rows, 1):
        status, body = probe(row["apiKey"])
        if status == 429:
            time.sleep(RETRY_429_SLEEP)
            status, body = probe(row["apiKey"])
        if status == 200:
            verdict = "ok"
            ok += 1
        elif status in (401, 403):
            verdict = "dead"
            dead += 1
        else:
            verdict = "unknown"
            unknown += 1
        rec = {"email": row["email"], "id": row["id"], "status": status,
               "verdict": verdict, "body": body[:120]}
        out.write(json.dumps(rec) + "\n")
        out.flush()
        print(f"[{i}/{len(rows)}] {verdict:7} {status:>3} {row['email']}", flush=True)
        time.sleep(SLEEP)
    out.close()
    print(f"SUMMARY ok={ok} dead={dead} unknown={unknown} of {len(rows)}")


if __name__ == "__main__":
    main()
"""merge_accounts.py — read legacy accounts.json (line‑delimited JSON) and accounts_new.json, produce accounts_all.json with 30 entries.
If the legacy file is corrupted (multiple JSON objects concatenated), we parse line‑by‑line.
"""
import json, pathlib

legacy_path = pathlib.Path(r"D:\tokenharbor-farmer\accounts.json")
new_path = pathlib.Path(r"D:\tokenharbor-farmer\accounts_new.json")
out_path = pathlib.Path(r"D:\tokenharbor-farmer\accounts_all.json")

legacy = []
if legacy_path.exists():
    for line in legacy_path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            legacy.append(json.loads(line))
        except Exception:
            # try to split by '}{' pattern (multiple objects in one line)
            parts = line.replace('}{', '}\n{').split('\n')
            for p in parts:
                try:
                    legacy.append(json.loads(p))
                except Exception:
                    pass

new = []
if new_path.exists():
    new = json.loads(new_path.read_text())

# deduplicate by email
seen = set()
merged = []
for rec in legacy + new:
    email = rec.get('email')
    if not email or email in seen:
        continue
    seen.add(email)
    merged.append(rec)

out_path.write_text(json.dumps(merged, indent=2))
print('merged count:', len(merged))

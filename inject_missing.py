"""inject_missing.py — inject any accounts_new.json entries missing from 9Router.
Dedup by email; idempotent (safe to re-run).
"""
import json, sqlite3, uuid
from datetime import datetime, timezone
from pathlib import Path

ACC = Path(r"D:\tokenharbor-farmer\accounts_new.json")
DB = Path.home() / "AppData" / "Roaming" / "9router" / "db" / "data.sqlite"

accounts = json.loads(ACC.read_text())
conn = sqlite3.connect(str(DB))
cur = conn.cursor()

emails_in_router = {r[0] for r in cur.execute(
    "SELECT email FROM providerConnections WHERE provider='tokenbor'").fetchall()}

added = 0
now = datetime.now(timezone.utc).isoformat()
for acc in accounts:
    email, key = acc["email"], acc["api_key"]
    if email in emails_in_router:
        continue
    count = cur.execute(
        "SELECT COUNT(*) FROM providerConnections WHERE provider='tokenbor'").fetchone()[0]
    label = f"{email.split('@')[0][:6]} #{count + 1}"
    data = json.dumps({
        "defaultModel": "deepseek-v4-flash:free",
        "apiKey": key,
        "testStatus": "active",
        "providerSpecificData": {
            "prefix": "tokenbor",
            "apiType": "chat",
            "baseUrl": "https://tokenharbor.ai/v1",
            "nodeName": "tokenbor",
        },
    })
    cur.execute(
        "INSERT INTO providerConnections (id, provider, authType, name, email, priority, isActive, data, createdAt, updatedAt) VALUES (?, 'tokenbor', 'api_key', ?, ?, 0, 1, ?, ?, ?)",
        (str(uuid.uuid4()), label, email, data, now, now))
    print(f"  injected: {email} -> {label}")
    added += 1

conn.commit()
total = cur.execute(
    "SELECT COUNT(*) FROM providerConnections WHERE provider='tokenbor'").fetchone()[0]
conn.close()
print(f"\nAdded {added}; total tokenbor in 9Router: {total}")

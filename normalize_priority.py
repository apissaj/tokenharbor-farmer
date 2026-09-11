"""Normalize 9Router TH priorities: oldest account = highest priority (N...1).

Run after every batch so newly injected accounts (priority 0) get slotted
at the bottom of the order. Oldest account always used first by 9Router.
"""
import sqlite3
from pathlib import Path

DB = Path(r"C:\Users\TUF Gaming A15\AppData\Roaming\9router\db\data.sqlite")
TARGET = "openai-compatible-chat-07ede055-d26a-4690-9e3b-b1930b247502"

conn = sqlite3.connect(str(DB), timeout=30)
cur = conn.cursor()
rows = cur.execute(
    "SELECT id FROM providerConnections WHERE provider=? ORDER BY createdAt ASC, id ASC",
    (TARGET,)).fetchall()
total = len(rows)
for i, (rid,) in enumerate(rows):
    cur.execute("UPDATE providerConnections SET priority=? WHERE id=?", (total - i, rid))
conn.commit()
conn.close()
print(f"[priority] {total} akun TH dinormalisasi: tertua={total} -> terbaru=1")

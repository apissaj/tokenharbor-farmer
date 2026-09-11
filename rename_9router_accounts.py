"""rename_9router_accounts.py
Generate realistic Indonesian display names for TokenHarbor accounts.
Replace user names like 'useraaa001883' with 'Andika Pratama' etc.
Updates:
  - 9Router SQLite: providerConnections.name (only entries created by us, i.e. with non-empty email)
  - accounts_new.json: name field added/updated

Strategy: round-robin through a curated pool of 60 Indonesian full names (first + last).
Per-email deterministic index via hash(email) so renames are stable across re-runs.
"""

import sqlite3, json, hashlib, os
from datetime import datetime, timezone

DB = r'C:\Users\TUF Gaming A15\AppData\Roaming\9router\db\data.sqlite'
ACCOUNTS = r'D:\tokenharbor-farmer\accounts_new.json'

# Indonesian name pool — common real names, neutral & varied.
NAMA_DEPAN = [
    "Andika","Budi","Citra","Dewi","Eka","Fajar","Galih","Hendra","Indah","Joko",
    "Kartika","Lutfi","Mahesa","Nanda","Okta","Putri","Rangga","Sari","Tegar","Utami",
    "Vina","Wahyu","Yanto","Zara","Bagus","Cahya","Dian","Endah","Fadhil","Gita",
    "Hadi","Indra","Jihan","Krisna","Laras","Maulana","Naufal","Olivia","Pandu","Ratna",
    "Surya","Tantri","Ujang","Vikri","Wulan","Yusuf","Aulia","Bagas","Cinta","Dimas",
    "Ervan","Fanny","Gilang","Hesti","Irfan","Jelita","Kania","Lutfi","Maulida","Naufal"
]
NAMA_BELAKANG = [
    "Pratama","Wijaya","Saputra","Putri","Lestari","Hidayat","Nugroho","Anggraini","Maulana","Sari",
    "Permata","Wibowo","Setiawan","Ananda","Maharani","Suryanto","Halim","Cahyani","Pradipta","Mahardika",
    "Kusuma","Rachman","Prasetyo","Adiputra","Nugraha","Hardiansyah","Firmansyah","Widodo","Sasmita","Tandilangi"
]

def pick_name(seed: str) -> str:
    h = hashlib.md5(seed.encode()).hexdigest()
    i_depan = int(h[:4], 16) % len(NAMA_DEPAN)
    i_belakang = int(h[4:8], 16) % len(NAMA_BELAKANG)
    return f"{NAMA_DEPAN[i_depan]} {NAMA_BELAKANG[i_belakang]}"

# 1. Load accounts
with open(ACCOUNTS) as f:
    accs = json.load(f)

# 2. Build mapping: apiKey → display name
mapping = {}
for a in accs:
    email = a['email']
    api_key = a.get('api_key')
    if not api_key:
        continue
    mapping[api_key] = {
        'display_name': pick_name(email),
        'email': email,
    }

print(f"Generated {len(mapping)} display names.")

# 3. Update SQLite
conn = sqlite3.connect(DB)
cur = conn.cursor()
now_iso = datetime.now(timezone.utc).isoformat()
updated_db = 0
missing = []
for api_key, m in mapping.items():
    row = cur.execute(
        "SELECT id, name FROM providerConnections WHERE data LIKE ? LIMIT 1",
        (f'%{api_key}%',)
    ).fetchone()
    if not row:
        missing.append(api_key[:25])
        continue
    cur.execute(
        "UPDATE providerConnections SET name=?, updatedAt=? WHERE id=?",
        (m['display_name'], now_iso, row[0])
    )
    updated_db += 1

conn.commit()
print(f"Updated in DB: {updated_db}")
if missing:
    print(f"Missing keys (no matching DB row): {len(missing)}")
    print('  samples:', missing[:5])
conn.close()

# 4. Update accounts_new.json — add display_name field
for a in accs:
    if a.get('api_key') in mapping:
        a['display_name'] = mapping[a['api_key']]['display_name']

with open(ACCOUNTS, 'w') as f:
    json.dump(accs, f, indent=2, ensure_ascii=False)

print("Updated accounts_new.json")
print()
print("=== Sample names ===")
for a in accs[:10]:
    print(f"  {a['email']:<40} -> {a.get('display_name','??')}")

"""Quick-fix: reset flag errorCode/testStatus/unavailable semua slot TokenHarbor di 9Router.

Error "The last message must have role=user" = 400 dari upstream TokenHarbor saat
di-test oleh availability checker 9Router (payload test-nya diakhiri role non-user).
Akunnya sehat — flag ini false-positive. Jalankan script ini untuk reset massal.

Pakai: python unflag_th.py
"""
import sqlite3
import json
import shutil
import time
from datetime import datetime

DB = r"C:\Users\TUF Gaming A15\AppData\Roaming\9router\db\data.sqlite"
TH_PROVIDER = "openai-compatible-chat-07ede055-d26a-4690-9e3b-b1930b247502"


def main():
    conn = sqlite3.connect(DB)
    conn.execute("PRAGMA busy_timeout=5000")

    flagged, = conn.execute(
        "SELECT COUNT(*) FROM providerConnections WHERE provider=? AND json_extract(data,'$.errorCode') IS NOT NULL",
        (TH_PROVIDER,),
    ).fetchone()

    if flagged == 0:
        print("OK: 0 slot ter-flag, tidak ada yang perlu di-fix.")
        conn.close()
        return

    # backup dulu
    bak = DB + f".bak_unflag_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    shutil.copy2(DB, bak)
    print(f"Backup: {bak}")

    cur = conn.execute(
        """
        UPDATE providerConnections
        SET data = json_set(data,
                '$.testStatus', 'active',
                '$.errorCode', NULL,
                '$.lastError', NULL)
        WHERE provider = ?
          AND json_extract(data, '$.errorCode') IS NOT NULL
        """,
        (TH_PROVIDER,),
    )
    conn.commit()
    print(f"Reset {cur.rowcount} slot -> testStatus=active")

    # verifikasi
    still, = conn.execute(
        "SELECT COUNT(*) FROM providerConnections WHERE provider=? AND json_extract(data,'$.errorCode') IS NOT NULL",
        (TH_PROVIDER,),
    ).fetchone()
    active, = conn.execute(
        "SELECT COUNT(*) FROM providerConnections WHERE provider=? AND isActive=1",
        (TH_PROVIDER,),
    ).fetchone()
    print(f"Verifikasi: ter-flag={still} | active={active}")
    conn.close()


if __name__ == "__main__":
    main()

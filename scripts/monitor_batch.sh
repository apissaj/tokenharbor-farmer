#!/bin/bash
# TokenHarbor batch monitor - cron wrapper
LATEST=$(ls -t /d/tokenharbor-farmer/logs/continuous_run*.log /d/tokenharbor-farmer/logs/continuous_restart*.log /d/tokenharbor-farmer/logs/batch_100_*.log 2>/dev/null | head -n 1)
echo "FILE: $LATEST"
if [ -z "$LATEST" ]; then
  echo "NO_LOG_FOUND"
  exit 0
fi
MTIME_TS=$(stat -c %Y "$LATEST" 2>/dev/null || stat -f %m "$LATEST")
NOW_TS=$(date +%s)
AGE=$((NOW_TS - MTIME_TS))
echo "MTIME: $(date -r "$LATEST" +%H:%M:%S) | NOW: $(date +%H:%M:%S) | AGE: ${AGE}s"
echo "INJECTED: $(grep -c 'Injected:' "$LATEST")"
echo "TEST_FAIL: $(grep -c 'model:N' "$LATEST")"
echo "RATE_MENTIONS: $(grep -c 'rate-limited' "$LATEST")"
echo "--- LAST BATCH DONE ---"
grep 'BATCH.*DONE' "$LATEST" | tail -n 3
echo "---"
echo "FINISHED: $(grep -c 'CONTINUOUS MODE FINISHED' "$LATEST")"

# TH pool from 9Router SQLite
python <<'PYEOF'
import sqlite3, os
db = r'C:\Users\TUF Gaming A15\AppData\Roaming\9router\db\data.sqlite'
if os.path.exists(db):
    try:
        conn = sqlite3.connect(db)
        cur = conn.cursor()
        cur.execute("SELECT count(*) FROM providerConnections WHERE provider LIKE 'openai-compatible-chat-07ede055%'")
        print('TH_POOL:', cur.fetchone()[0])
        conn.close()
    except Exception as e:
        print('TH_POOL_ERR:', e)
else:
    print('TH_POOL: db_missing')
PYEOF
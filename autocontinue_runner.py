"""Auto-continue runner: starts continuous_batches.py writing to a timestamped log
that matches the batch_100_*.log pattern so monitors keep tracking it."""
import subprocess
import sys
from datetime import datetime

FARMER = r"D:\tokenharbor-farmer\continuous_batches.py"
TAG = datetime.now().strftime("%Y%m%d_%H%M%S")
LOG = rf"D:\tokenharbor-farmer\logs\batch_100_{TAG}.log"

with open(LOG, "w", encoding="utf-8", errors="replace") as f:
    p = subprocess.Popen(
        [sys.executable, FARMER],
        cwd=r"D:\tokenharbor-farmer",
        stdout=f,
        stderr=subprocess.STDOUT,
    )
    p.wait()
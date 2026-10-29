"""Совместимый запускатель. Основной монитор находится в src/live_monitor.py."""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
TARGET = ROOT / "src" / "live_monitor.py"

if __name__ == "__main__":
    if not TARGET.exists():
        raise SystemExit(f"Не найден основной монитор: {TARGET}")
    raise SystemExit(subprocess.call([sys.executable, str(TARGET)], cwd=ROOT))

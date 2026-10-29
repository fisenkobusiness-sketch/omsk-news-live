"""Совместимый запускатель. Основной анализатор находится в src/analysis.py."""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
TARGET = ROOT / "src" / "analysis.py"

if __name__ == "__main__":
    if not TARGET.exists():
        raise SystemExit(f"Не найден основной анализатор: {TARGET}")
    raise SystemExit(subprocess.call([sys.executable, str(TARGET)], cwd=ROOT))

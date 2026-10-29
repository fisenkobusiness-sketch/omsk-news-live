"""Совместимый запускатель. Единственная актуальная модель — src/predictor.py."""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
TARGET = ROOT / "src" / "predictor.py"

if __name__ == "__main__":
    if not TARGET.exists():
        raise SystemExit(f"Не найден актуальный предиктор: {TARGET}")
    raise SystemExit(subprocess.call([sys.executable, str(TARGET)], cwd=ROOT))

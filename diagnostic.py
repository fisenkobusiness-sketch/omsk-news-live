"""Совместимый запускатель диагностики из tools/diagnostic.py."""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
TARGET = ROOT / "tools" / "diagnostic.py"

if __name__ == "__main__":
    if not TARGET.exists():
        raise SystemExit(f"Не найден диагностический инструмент: {TARGET}")
    raise SystemExit(subprocess.call([sys.executable, str(TARGET), *sys.argv[1:]], cwd=ROOT))

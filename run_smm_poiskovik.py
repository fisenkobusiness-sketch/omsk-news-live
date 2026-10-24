# -*- coding: utf-8 -*-
"""Один запуск: основной монитор + независимый трекер вовлечённости."""
from __future__ import annotations
import subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PROCESSES: list[subprocess.Popen] = []

def main() -> int:
    scripts = [ROOT / "src" / "live_monitor.py", ROOT / "src" / "smm_poiskovik_engagement_tracker.py"]
    for path in scripts:
        if not path.exists():
            raise SystemExit(f"Не найден файл: {path}")
    print("Запуск СММ Поисковика: монитор + контроль вовлечённости.", flush=True)
    print("Для остановки обоих процессов нажмите Ctrl+C.", flush=True)
    try:
        for path in scripts:
            PROCESSES.append(subprocess.Popen([sys.executable, str(path)], cwd=ROOT))
            time.sleep(2)
        while True:
            for process in PROCESSES:
                code = process.poll()
                if code is not None:
                    print(f"Процесс {process.args[-1]} завершился с кодом {code}. Второй процесс продолжает работу.", flush=True)
                    return code
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nОстанавливаю монитор и трекер...", flush=True)
        return 0
    finally:
        for process in PROCESSES:
            if process.poll() is None:
                process.terminate()
        deadline = time.time() + 10
        for process in PROCESSES:
            if process.poll() is None:
                try: process.wait(timeout=max(0.1, deadline - time.time()))
                except subprocess.TimeoutExpired: process.kill()
        print("Оба процесса остановлены.", flush=True)

if __name__ == "__main__":
    raise SystemExit(main())

# -*- coding: utf-8 -*-
"""Обратная совместимость: запуск основного VK-коллектора."""
from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parent
runpy.run_path(
    str(ROOT / "scripts" / "01_collect_vk.py"),
    run_name="__main__",
)

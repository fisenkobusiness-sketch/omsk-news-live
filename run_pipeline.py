# -*- coding: utf-8 -*-
"""Главный запуск проекта.

По умолчанию:
    02 → 03 → 04 → 05

Быстрый ежедневный режим:
    python run_pipeline.py --score-only

Для обновления истории VK:
    python run_pipeline.py --collect
"""
import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

FULL_STEPS = [
    ("scripts/02_build_dataset.py", "Сборка общего dataset"),
    ("scripts/03_analyze_audience.py", "Анализ двух аудиторий + профили"),
    ("scripts/04_build_editorial_model.py", "Построение двух редакторских моделей"),
    ("scripts/05_score_news.py", "Оценка свежих новостей + Audience Separator"),
]

SCORE_ONLY_STEPS = [
    ("scripts/05_score_news.py", "Быстрая оценка свежих новостей"),
]


def check_project():
    required = [
        "config.py",
        "lib/analytics_core.py",
        "lib/audience_router.py",
        "scripts/01_collect_vk.py",
        "scripts/02_build_dataset.py",
        "scripts/03_analyze_audience.py",
        "scripts/04_build_editorial_model.py",
        "scripts/05_score_news.py",
    ]

    missing = [
        str(BASE_DIR / path)
        for path in required
        if not (BASE_DIR / path).exists()
    ]

    if missing:
        print(
            "Не хватает файлов проекта:"
        )
        for path in missing:
            print(
                f"  - {path}"
            )
        raise SystemExit(2)


def run_step(script_name, title):
    path = BASE_DIR / script_name

    print()
    print("=" * 70)
    print(f"▶ {title}")
    print(f"  {script_name}")
    print("=" * 70)

    started = time.perf_counter()

    result = subprocess.run(
        [
            sys.executable,
            "-u",
            str(path),
        ],
        cwd=BASE_DIR,
        env={
            **os.environ,
            "PYTHONIOENCODING": "utf-8",
        },
    )

    elapsed = (
        time.perf_counter()
        - started
    )

    if result.returncode != 0:
        print()
        print(
            f"❌ ЭТАП ОСТАНОВЛЕН: "
            f"{script_name}"
        )
        print(
            f"Код завершения: "
            f"{result.returncode}"
        )
        print(
            f"Время: {elapsed:.1f} сек."
        )
        raise SystemExit(
            result.returncode
        )

    print(
        f"✓ Готово за {elapsed:.1f} сек."
    )


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Анализатор контента "
            "для двух VK-аудиторий"
        )
    )

    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--collect",
        action="store_true",
        help="Сначала обновить RAW через VK API.",
    )
    mode.add_argument(
        "--score-only",
        action="store_true",
        help=(
            "Не пересобирать dataset и модели; "
            "только пересчитать свежие новости."
        ),
    )

    args = parser.parse_args()

    check_project()

    print("=" * 70)
    print(
        "АНАЛИЗАТОР КОНТЕНТА — "
        "ДВЕ VK-АУДИТОРИИ"
    )
    print("=" * 70)
    print(
        f"Python: {sys.executable}"
    )
    print(
        f"Проект: {BASE_DIR}"
    )

    started = time.perf_counter()

    if args.collect:
        run_step(
            "scripts/01_collect_vk.py",
            "Обновление RAW из VK",
        )

    steps = (
        SCORE_ONLY_STEPS
        if args.score_only
        else FULL_STEPS
    )

    for script_name, title in steps:
        run_step(
            script_name,
            title,
        )

    elapsed = (
        time.perf_counter()
        - started
    )

    print()
    print("=" * 70)
    print(
        "✅ PIPELINE УСПЕШНО ЗАВЕРШЁН"
    )
    print(
        f"Общее время: {elapsed:.1f} сек."
    )
    print("=" * 70)
    print()
    print(
        "Audience Separator сейчас "
        "работает в режиме DIAGNOSTIC_ONLY."
    )
    print(
        "Он показывает, какой паблик подходит "
        "лучше, но не публикует автоматически."
    )


if __name__ == "__main__":
    main()

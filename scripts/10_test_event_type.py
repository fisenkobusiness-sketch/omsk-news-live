# -*- coding: utf-8 -*-
"""Focused regression tests for editorial event type classification.

Run with:
    python scripts/10_test_event_type.py

This test suite is separate from clustering identity tests: event-type changes
are applied after NewsEvent clustering and therefore must not merge/split events.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from events.editorial_event_type import classify_editorial_event_type


CASES = [
    (
        "UAVs shot down are not a road accident",
        "113 дронов сбили над Россией: в Омске слышали взрывы, один БПЛА достиг промзоны",
        "general",
    ),
    (
        "UAV attack with no casualties is not politics just because of follow-up context",
        "При атаке вражеских БПЛА на Омск никто не пострадал",
        "general",
    ),
    (
        "fire with flames above poles is fire, not accident",
        "Пламя выше столбов и искры во все стороны: в крупном пожаре на 27-й Рабочей пострадала омичка",
        "fire",
    ),
    (
        "fire service commemorative day is not an active fire",
        "☀ Доброе утро, омичи! 9 октября, в России отмечают День Специальной пожарной охраны МЧС",
        "general",
    ),
    (
        "proposed regional budget revision is politics, not transport",
        "В Омской области планируют увеличить бюджет на 13 млрд рублей. На что направят эти деньги?",
        "politics",
    ),
    (
        "teacher stipends are social, not crime",
        "Почти 22 миллиона: Хоценко направил дополнительные средства на стипендии будущим педагогам",
        "social",
    ),
    (
        "annual budget revenue growth is a budget/policy story",
        "Доходы бюджета Омской области за год выросли на 8,7 миллиарда рублей",
        "politics",
    ),
    (
        "temperature forecast is weather",
        "На выходных в Омской области потеплеет до +14 градусов — прогноз на три дня",
        "weather",
    ),
    (
        "magnetic storms are weather",
        "Омичей предупредили о магнитных бурях из-за всплеска солнечной активности",
        "weather",
    ),
    (
        "cancelled electric train is transport",
        "В Омске отменили ежедневную электричку до дач",
        "transport",
    ),
    (
        "flight route is transport",
        "Омичи смогут летать зимой на популярный курорт Кавказа",
        "transport",
    ),
    (
        "airport delay is transport",
        "Омичи застряли в аэропорту почти на 12 часов",
        "transport",
    ),
    (
        "traffic police annual report is transport reporting, not an individual crash",
        "В Госавтоинспекции Омской области подвели итоги работы за 9 месяцев 2026 года",
        "transport",
    ),
    (
        "heating and hot-water complaint is social",
        "Вот интересно! Когда услуга не подаётся, почему не делают перерасчёт? Отопление есть только в половине квартиры, горячая вода грязная",
        "social",
    ),
    (
        "tire-supplier productivity story is general, not politics from body context",
        "Бережливые технологии помогли омскому поставщику шин сократить время отгрузки на маркетплейсы",
        "general",
    ),
    (
        "memorial opening attended by city leader is general",
        "Шелест принял участие в открытии памятного знака земляку, погибшему при штурме дворца Амина",
        "general",
    ),
    (
        "government appointment is politics",
        "В правительстве Омской области назначили начальников двух главных управлений",
        "politics",
    ),
    (
        "building project associated with a deputy is not automatically politics",
        "В Омске появится многоэтажка от депутата",
        "general",
    ),
    (
        "Honda crash is accident",
        "Двое детей пострадали в ДТП на улице 70 лет Октября: Honda врезалась в столб",
        "accident",
    ),
    (
        "fatal bus collision is accident",
        "Пассажирский автобус насмерть сбил пожилого омича",
        "accident",
    ),
    (
        "court conviction for domestic violence is crime",
        "Омич получил 9 лет за избиение жены, которая погибла после побоев",
        "crime",
    ),
    (
        "salary additions for public employees are social",
        "В Омской области добавят 2,5 миллиарда рублей на зарплаты бюджетникам",
        "social",
    ),
    (
        "planned siren test stays general under the current taxonomy",
        "Сегодня в Омске проверят сирены и громкоговорители. Это плановая проверка системы оповещения",
        "general",
    ),
    (
        "bridge repair is transport",
        "Ремонт моста имени 60-летия ВЛКСМ через Иртыш значительно отстаёт от графика",
        "transport",
    ),
    (
        "pedestrian traffic scheme change is transport",
        "На Соборной площади в Омске изменят схему движения",
        "transport",
    ),
]


def main() -> None:
    failures = []
    for name, text, expected in CASES:
        actual = classify_editorial_event_type(text)
        if actual != expected:
            failures.append((name, expected, actual, text))
        else:
            print(f"OK: {name} -> {actual}")
    if failures:
        for name, expected, actual, text in failures:
            print(f"FAIL: {name}: expected={expected}, actual={actual} | {text}")
        raise SystemExit(f"{len(failures)} event-type test(s) failed out of {len(CASES)}")
    print(f"All {len(CASES)} editorial event-type tests passed.")


if __name__ == "__main__":
    main()

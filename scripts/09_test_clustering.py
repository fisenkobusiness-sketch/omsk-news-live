# -*- coding: utf-8 -*-
"""Regression checks for high-confidence news-event deduplication.

Run locally with:
    python scripts/09_test_clustering.py

These examples protect against merging unrelated crime/infrastructure stories
while retaining clear duplicate-accident and planned-siren matches.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from events.clustering import cluster_source_posts


def source_post(
    *,
    platform: str,
    source_id: str,
    source_name: str,
    published_at: str,
    text: str,
    publisher: str | None = None,
) -> dict:
    digest = hashlib.sha1(
        f"{platform}|{source_id}|{published_at}|{text}".encode("utf-8")
    ).hexdigest()
    row = {
        "source": {
            "platform": platform,
            "source_id": source_id,
            "source_name": source_name,
        },
        "post": {
            "id": digest,
            "url": f"https://example.invalid/{digest}",
            "published_at": published_at,
            "text": text,
        },
        "meta": {},
    }
    if publisher:
        row["meta"]["publisher"] = publisher
        row["meta"]["description"] = text
    return row


def check(name: str, posts: list[dict], expected_events: int) -> None:
    events = cluster_source_posts(posts)
    actual = len(events)
    if actual != expected_events:
        summaries = [
            {
                "event_id": event.get("event_id"),
                "sources": [
                    (p.get("source") or {}).get("source_name")
                    for p in event.get("source_posts") or []
                ],
                "text": (event.get("canonical_text") or "")[:180],
                "reasons": event.get("cluster_reasons", []),
                "last_reason": event.get("cluster_reason_last"),
            }
            for event in events
        ]
        raise AssertionError(
            f"{name}: ожидалось событий {expected_events}, получено {actual}. "
            f"Результат: {summaries}"
        )
    print(f"OK: {name} -> {actual} event(s)")


def main() -> None:
    # False positive from the actual discovery sample:
    # scam gang has "Telegram" and "обвиняют", as does the unrelated Rybar case.
    fraud = source_post(
        platform="vk",
        source_id="fraud_group",
        source_name="Жесть Омска",
        published_at="2026-10-09T05:34:56Z",
        text=(
            "В Омске начнут судить банду телефонных мошенников. Перед судом "
            "предстанет 21 человек, которых обвиняют в мошенничестве. "
            "Работу курьеров контролировали через Telegram."
        ),
    )
    rybar = source_post(
        platform="web_search",
        source_id="ngs55",
        source_name="NGS55.RU",
        publisher="NGS55.RU",
        published_at="2026-10-09T09:01:48Z",
        text=(
            "Создателя Telegram-канала «Рыбарь» задержали: Михаила Звинчука "
            "обвиняют в пропаганде - NGS55.RU"
        ),
    )
    check("unrelated crime stories stay separate", [fraud, rybar], 2)

    lights_ngs = source_post(
        platform="web_search",
        source_id="ngs55_lights",
        source_name="NGS55.RU",
        publisher="NGS55.RU",
        published_at="2026-10-09T07:14:09Z",
        text=(
            "«Половина светильников сломана»: в сквере «Юбилейный» "
            "орудуют вандалы - NGS55.RU"
        ),
    )
    lights_vk = source_post(
        platform="vk",
        source_id="incident_lights",
        source_name="Аварийный Омск",
        published_at="2026-10-09T08:44:55Z",
        text=(
            "Прошел практически год, как Омскэлектро меняют два светильника "
            "на ул. Куйбышева и ул. Лазо, но не ставят обратно."
        ),
    )
    check("unrelated lighting reports stay separate", [lights_ngs, lights_vk], 2)

    honda_vk = source_post(
        platform="vk",
        source_id="incident_honda",
        source_name="Инцидент Омск",
        published_at="2026-10-09T04:23:17Z",
        text=(
            "В Омске автоледи устроила аварию возле «Континента» на улице "
            "70 лет Октября. 35-летняя женщина на Honda не справилась с "
            "управлением и врезалась в столб. Пострадали двое детей: "
            "мальчик 5 лет и девочка 7 лет."
        ),
    )
    honda_ngs = source_post(
        platform="web_search",
        source_id="ngs55_honda",
        source_name="NGS55.RU",
        publisher="NGS55.RU",
        published_at="2026-10-09T05:14:14Z",
        text=(
            "Пострадали двое детей: рядом с «Континентом» иномарка "
            "влетела в столб - NGS55.RU"
        ),
    )
    check("same Honda crash merges across sources", [honda_vk, honda_ngs], 1)

    bus_short = source_post(
        platform="vk",
        source_id="chp_bus",
        source_name="ЧП Омск",
        published_at="2026-10-09T04:05:30Z",
        text=(
            "На ул. Заозёрная автобус сбил человека, предположительно "
            "на пешеходном переходе."
        ),
    )
    bus_full = source_post(
        platform="vk",
        source_id="live_bus",
        source_name="Омск Live",
        published_at="2026-10-09T06:47:00Z",
        text=(
            "Пассажирский автобус насмерть сбил пожилого омича. В районе "
            "остановки «7-я Заозёрная» водитель автобуса МАЗ совершил "
            "наезд на человека на нерегулируемом пешеходном переходе. "
            "Погибшим оказался 66-летний мужчина."
        ),
    )
    check("same fatal bus crash merges across sources", [bus_short, bus_full], 1)

    siren_vk = source_post(
        platform="vk",
        source_id="omsk_alerts",
        source_name="12 Канал",
        published_at="2026-10-09T03:31:39Z",
        text=(
            "Сегодня в Омске с 10:35 до 10:43 проверят сирены и "
            "громкоговорители. Это плановая проверка системы оповещения."
        ),
    )
    siren_web = source_post(
        platform="web_search",
        source_id="omsk_web",
        source_name="Вечерний Омск",
        publisher="Вечерний Омск",
        published_at="2026-10-09T03:47:51Z",
        text="Омичам напоминают о проверке систем оповещения.",
    )
    check("same planned siren check merges", [siren_vk, siren_web], 1)

    national_sirens = source_post(
        platform="web_search",
        source_id="ngs_national",
        source_name="NGS55.RU",
        publisher="NGS55.RU",
        published_at="2026-10-09T03:40:00Z",
        text=(
            "По всей стране враз завыли сирены и заработали "
            "громкоговорители: что случилось - NGS55.RU"
        ),
    )
    check(
        "nationwide siren headline does not auto-merge into local planned test",
        [siren_vk, national_sirens],
        2,
    )


    # Two different crashes happened in different locations in Omsk on the same
    # morning. Similar vehicle/casualty words must not merge them.
    bus_different = source_post(
        platform="vk",
        source_id="bus_at_zaozernaya",
        source_name="ЧП Омск",
        published_at="2026-10-09T04:05:30Z",
        text=(
            "На ул. Заозёрная автобус сбил человека, предположительно "
            "на пешеходном переходе."
        ),
    )
    honda_different = source_post(
        platform="web_search",
        source_id="ngs55_honda_different",
        source_name="NGS55.RU",
        publisher="NGS55.RU",
        published_at="2026-10-09T05:14:14Z",
        text=(
            "Пострадали двое детей: рядом с «Континентом» иномарка "
            "влетела в столб - NGS55.RU"
        ),
    )
    check("bus crash and Honda crash at different locations stay separate",
          [bus_different, honda_different], 2)

    # Actual false merge from the sample: siren test versus preparation of
    # outdoor hockey rinks. Same city and same publication date are not identity.
    hockey_rinks = source_post(
        platform="vk",
        source_id="hockey_rinks",
        source_name="Омск ВК",
        published_at="2026-10-09T04:00:00Z",
        text=(
            "В Омске анонсировали процесс заливки хоккейных площадок. "
            "Хоккейные коробки необходимо залить в срок до 11 декабря 2026 года. "
            "В городской администрации сообщили о подготовке к зимнему периоду "
            "плоскостных спортивных сооружений."
        ),
    )
    check("planned siren check and hockey rink preparation stay separate",
          [siren_vk, hockey_rinks], 2)

    # Same publisher and governor name, but different story: budget amendment
    # versus a statement about people responding to a drone attack.
    budget_story = source_post(
        platform="web_search",
        source_id="budget_query",
        source_name="СуперОмск",
        publisher="СуперОмск",
        published_at="2026-10-09T03:29:00Z",
        text=(
            "Хоценко: доходы бюджета Омской области предложено увеличить "
            "на 8,7 млрд рублей - СуперОмск"
        ),
    )
    drone_statement = source_post(
        platform="web_search",
        source_id="governor_statement_query",
        source_name="СуперОмск",
        publisher="СуперОмск",
        published_at="2026-10-09T03:41:00Z",
        text=(
            "Хоценко обратился к отражавшим атаку БПЛА на Омскую область "
            "- СуперОмск"
        ),
    )
    check("budget story and governor drone-attack statement stay separate",
          [budget_story, drone_statement], 2)

    # Common opener phrases like "Доброе утро, Омск" do not turn a greeting
    # into the same event as a public complaint about heating and hot water.
    postal_day = source_post(
        platform="vk",
        source_id="postal_day",
        source_name="Om1",
        published_at="2026-10-09T03:12:41Z",
        text=(
            "Доброе утро, Омск! Сегодня — Всемирный день почты! "
            "Праздник напоминает о временах, когда письма ждали неделями."
        ),
    )
    hot_water_complaint = source_post(
        platform="vk",
        source_id="hot_water_complaint",
        source_name="Аварийный Омск",
        published_at="2026-10-09T03:17:38Z",
        text=(
            "Доброе утро! Администрация города Омска, примите меры. "
            "По улице Магистральная, дома 56А и 56Б, третью неделю без "
            "горячей воды и отопления."
        ),
    )
    check("morning greeting and heating complaint stay separate",
          [postal_day, hot_water_complaint], 2)


    # Regression case from the real discovery batch: multiple unrelated
    # accidents/reports plus crime and a memorial notice were chained into
    # one NewsEvent by the location/detail shortcut. All six must stay separate.
    traffic_daily = source_post(
        platform="vk",
        source_id="traffic_daily",
        source_name="Госавтоинспекция Омской области",
        published_at="2026-10-09T03:42:06Z",
        text=(
            "Итоги суток 8 октября 2026 года. За сутки на дорогах Омской области "
            "зарегистрировано 5 ДТП, в которых 1 человек погиб и 8 получили травмы. "
            "Возбуждено 496 административных дел."
        ),
    )
    honda_on_70 = source_post(
        platform="vk",
        source_id="honda_on_70",
        source_name="ЧП Омск",
        published_at="2026-10-09T04:23:17Z",
        text=(
            "Двое детей пострадали в ДТП на улице 70 лет Октября. 35-летняя "
            "женщина на Honda потеряла управление и врезалась в фонарный столб "
            "возле дома № 5к4. Мальчик 5 лет и девочка 7 лет госпитализированы."
        ),
    )
    fire_27_work = source_post(
        platform="vk",
        source_id="fire_27_work",
        source_name="ЧП Омск",
        published_at="2026-10-09T04:24:00Z",
        text=(
            "Накануне поздно вечером на 27-й Рабочей полыхал жилой дом и постройки. "
            "Горели квартира, кровля, кочегарка, баня и дровяник. На пожаре получила "
            "травмы женщина."
        ),
    )
    traffic_summary = source_post(
        platform="vk",
        source_id="traffic_summary",
        source_name="Госавтоинспекция Омской области",
        published_at="2026-10-09T04:52:16Z",
        text=(
            "В Госавтоинспекции подвели итоги за 9 месяцев 2026 года. В Омской "
            "области зарегистрировано 1 737 ДТП, в которых 102 человека погибли "
            "и 2 190 получили травмы."
        ),
    )
    fraud_case = source_post(
        platform="vk",
        source_id="fraud_case",
        source_name="Жесть Омска",
        published_at="2026-10-09T05:34:56Z",
        text=(
            "В Омске начнут судить банду телефонных мошенников. Перед судом "
            "предстанет 21 человек, обвиняемых в мошенничестве. Курьеров "
            "контролировали через Telegram."
        ),
    )
    memorial = source_post(
        platform="vk",
        source_id="memorial",
        source_name="Om1",
        published_at="2026-10-09T08:31:11Z",
        text=(
            "Шелест принял участие в открытии памятного знака Борису Суворову. "
            "В Омске открыли памятный знак участнику боевых действий в Афганистане. "
            "Для монумента выбрали сквер, названный в честь Суворова."
        ),
    )
    check(
        "unrelated posts from actual contaminated event stay separate",
        [traffic_daily, honda_on_70, fire_27_work, traffic_summary, fraud_case, memorial],
        6,
    )


if __name__ == "__main__":
    main()

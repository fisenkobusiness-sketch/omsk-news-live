# -*- coding: utf-8 -*-
"""Build a clickable editorial review page from current discovery outputs.

VK + Web Search events use the existing deterministic deduplication,
regional filter and diagnostic audience router.
Telegram public previews are shown separately for manual review only and are
not sent to the model/router. No media files are downloaded or embedded.
"""
from __future__ import annotations

import html
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

EVENTS_INPUT = ROOT / "data" / "events" / "routed_news_events.jsonl"
TELEGRAM_INPUT = ROOT / "data" / "normalized" / "telegram_public_posts.jsonl"
OUTPUT_DIR = ROOT / "data" / "events"
JSON_OUTPUT = OUTPUT_DIR / "editorial_queue.json"
HTML_OUTPUT = OUTPUT_DIR / "editorial_queue.html"

OMSK = timezone(timedelta(hours=6), name="Asia/Omsk")


def read_jsonl(path: Path, *, required: bool = True) -> list[dict[str, Any]]:
    if not path.exists():
        if required:
            raise FileNotFoundError(f"Не найден файл: {path}")
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Некорректный JSON в {path}, строка {line_number}: {exc}") from exc
    return rows


def safe_url(value: Any) -> str:
    url = str(value or "").strip()
    if url.startswith(("https://", "http://")):
        return url
    return ""


def local_time(value: Any) -> str:
    if not value:
        return "время неизвестно"
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(OMSK).strftime("%d.%m %H:%M Омск")
    except (TypeError, ValueError, OverflowError):
        return str(value)


def age_label(minutes: Any) -> str:
    if minutes is None:
        return "возраст неизвестен"
    try:
        n = max(0, int(float(minutes)))
    except (TypeError, ValueError):
        return "возраст неизвестен"
    if n < 60:
        return f"{n} мин. назад"
    if n < 24 * 60:
        return f"{n // 60} ч. назад"
    return f"{n // (24 * 60)} дн. назад"


def audience_label(value: Any) -> str:
    return {"golos": "Голос", "zhest": "Жесть"}.get(str(value or ""), "Не определено")


_AD_EXPLICIT_RE = re.compile(r"\b(?:реклама|erid\s*[:=])\b?", re.IGNORECASE)
_AD_STRONG_RE = re.compile(
    r"\b(?:скидк\w*|промокод\w*|распродаж\w*|купить|заказать|"
    r"запись и консультация|бесплатный подбор|только до \d{1,2}\s+\w+)\b",
    re.IGNORECASE,
)
_PHONE_RE = re.compile(r"(?:\+7|8)[\s(\\-]*\d{3}")


def _is_commercial_event(event: dict[str, Any]) -> bool:
    """Conservative queue-only ad gate; never changes the source or model data."""
    snippets = [str(event.get("canonical_text") or "")]
    for source_post in event.get("source_posts") or []:
        post = source_post.get("post") or {}
        snippets.append(str(post.get("text") or ""))
    text = "\n".join(snippets)
    if _AD_EXPLICIT_RE.search(text):
        return True

    strong_signals = len(_AD_STRONG_RE.findall(text))
    has_commercial_context = bool(
        re.search(r"\\b(?:салон|магазин|клиника|заказ|услуг|товар|стоимость|цена)\\w*\\b", text, re.I)
        or _PHONE_RE.search(text)
        or re.search(r"\\b\\d{1,2}\\s*%", text)
    )
    return strong_signals >= 2 and has_commercial_context


def build_payload(events: list[dict[str, Any]], telegram_posts: list[dict[str, Any]]) -> dict[str, Any]:
    prepared_events = []
    commercial_events = []
    for event in events:
        routing = event.get("audience_routing") or {}
        scores = event.get("audience_scores") or {}
        representative = event.get("representative_post") or {}
        representative_post = representative.get("post") or {}
        sources = []
        seen_urls: set[str] = set()
        for source_post in event.get("source_posts") or []:
            source = source_post.get("source") or {}
            post = source_post.get("post") or {}
            url = safe_url(post.get("url"))
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            sources.append({
                "platform": str(source.get("platform") or ""),
                "name": str(source.get("source_name") or source.get("source_id") or "Источник"),
                "url": url,
                "published_at": post.get("published_at"),
            })
        prepared_row = {
            "event_id": event.get("event_id"),
            "title": str(event.get("canonical_text") or representative_post.get("text") or "Без текста").strip(),
            "published_at": event.get("first_seen_at") or representative_post.get("published_at"),
            "freshness_age_minutes": event.get("freshness_age_minutes"),
            "event_type": event.get("event_type") or "general",
            "recommended_target": routing.get("recommended_target"),
            "route_decision": routing.get("decision"),
            "route_fit": routing.get("fit") or {},
            "score_golos": (scores.get("golos") or {}).get("editorial_score_absolute"),
            "score_zhest": (scores.get("zhest") or {}).get("editorial_score_absolute"),
            "source_count": event.get("source_count") or len(sources),
            "independent_source_count": event.get("independent_source_count"),
            "sources": sources,
        }
        if _is_commercial_event(event):
            prepared_row["editorial_exclusion"] = "Реклама или коммерческое предложение"
            commercial_events.append(prepared_row)
        else:
            prepared_events.append(prepared_row)

    for collection in (prepared_events, commercial_events):
        collection.sort(
            key=lambda row: (
                max((row.get("route_fit") or {}).values() or [0.0]),
                -(float(row.get("freshness_age_minutes") or 0)),
                int(row.get("source_count") or 0),
            ),
            reverse=True,
        )

    prepared_telegram = []
    seen_urls: set[str] = set()
    for post_row in telegram_posts:
        source = post_row.get("source") or {}
        post = post_row.get("post") or {}
        url = safe_url(post.get("url"))
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        text = str(post.get("text") or "").strip()
        signals = post_row.get("signals") or {}
        prepared_telegram.append({
            "source_name": str(source.get("source_name") or source.get("source_id") or "Telegram"),
            "source_id": str(source.get("source_id") or ""),
            "published_at": post.get("published_at"),
            "url": url,
            "text": text,
            "views": signals.get("views"),
            "media_types": (post_row.get("media") or {}).get("types") or [],
            "manual_review_only": True,
        })
    prepared_telegram.sort(key=lambda row: str(row.get("published_at") or ""), reverse=True)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "timezone": "Asia/Omsk",
        "counts": {
            "vk_web_events": len(prepared_events),
            "commercial_events": len(commercial_events),
            "vk_web_events_total": len(prepared_events) + len(commercial_events),
            "telegram_manual_posts": len(prepared_telegram),
        },
        "vk_web_events": prepared_events,
        "commercial_events": commercial_events,
        "telegram_manual_posts": prepared_telegram,
        "notes": [
            "VK/Web events use existing diagnostic regional relevance, deduplication and audience routing.",
            "Commercial or explicitly marked advertising posts are separated from the main news queue, not deleted from source data.",
            "Telegram posts are listed separately for manual editorial review; they are not scored or used for model training.",
            "Only original publication links are included. Images and videos are not downloaded or embedded.",
        ],
    }


def esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def render_event_card(event: dict[str, Any], rank: int) -> str:
    target = (
        "Реклама / коммерция"
        if event.get("editorial_exclusion")
        else audience_label(event.get("recommended_target"))
    )
    score_golos = event.get("score_golos")
    score_zhest = event.get("score_zhest")
    score_text = (
        f"Модельная оценка — Голос: {esc(score_golos if score_golos is not None else '—')}; "
        f"Жесть: {esc(score_zhest if score_zhest is not None else '—')}"
    )
    fit = event.get("route_fit") or {}
    fit_text = " · ".join(
        f"{esc(audience_label(key))}: {esc(value)}"
        for key, value in fit.items()
    ) or "оценка маршрутизатора недоступна"

    links = []
    for source in event.get("sources") or []:
        links.append(
            f'<a href="{esc(source["url"])}" target="_blank" rel="noopener noreferrer">'
            f'{esc(source["name"])} · {esc(source["platform"])} · открыть оригинал</a>'
        )
    links_html = "<br>".join(links) if links else "<span class=\"muted\">Нет прямой ссылки в источнике</span>"
    title = str(event.get("title") or "Без текста")
    snippet = title if len(title) <= 1100 else title[:1097] + "…"
    return f"""
    <article class="card">
      <div class="topline"><span class="rank">#{rank}</span><span class="tag">{esc(target)}</span>
      <span class="muted">{esc(event.get("event_type"))} · {esc(local_time(event.get("published_at")))} · {esc(age_label(event.get("freshness_age_minutes")))}</span></div>
      <h3>{esc(title[:180])}</h3>
      <p class="bodytext">{esc(snippet)}</p>
      <p class="scores">{score_text}</p>
      <p class="muted">Маршрутизатор: {fit_text} · Источников: {esc(event.get("source_count"))} · независимых: {esc(event.get("independent_source_count") if event.get("independent_source_count") is not None else "—")}</p>
      <div class="links">{links_html}</div>
    </article>
    """


def render_telegram_card(post: dict[str, Any]) -> str:
    content = str(post.get("text") or "").strip()
    if not content:
        content = "Публикация без текстовой подписи — открой оригинал для проверки."
    views = post.get("views")
    views_label = f" · просмотры: {esc(views)}" if views is not None else ""
    media = ", ".join(str(x) for x in post.get("media_types") or [])
    media_label = f" · тип: {esc(media)}" if media else ""
    return f"""
    <article class="card tgcard">
      <div class="topline"><span class="tag">Ручная проверка</span>
      <span class="muted">{esc(local_time(post.get("published_at")))}{views_label}{media_label}</span></div>
      <h3>{esc(post.get("source_name"))} (@{esc(post.get("source_id"))})</h3>
      <p class="bodytext">{esc(content[:850])}{'…' if len(content) > 850 else ''}</p>
      <div class="links"><a href="{esc(post.get('url'))}" target="_blank" rel="noopener noreferrer">Открыть публикацию в Telegram</a></div>
    </article>
    """


def render_html(payload: dict[str, Any]) -> str:
    events = payload["vk_web_events"]
    commercial = payload.get("commercial_events") or []
    telegram = payload["telegram_manual_posts"]
    generated = local_time(payload.get("generated_at"))
    event_cards = "".join(render_event_card(row, idx) for idx, row in enumerate(events, start=1))
    commercial_cards = "".join(render_event_card(row, idx) for idx, row in enumerate(commercial, start=1))
    telegram_cards = "".join(render_telegram_card(row) for row in telegram)
    if not event_cards:
        event_cards = '<p class="empty">Пока нет событий VK/Web. Сначала запусти discovery → events → route-events.</p>'
    if not commercial_cards:
        commercial_cards = '<p class="empty">Рекламных или явно коммерческих публикаций не найдено.</p>'
    if not telegram_cards:
        telegram_cards = '<p class="empty">Сегодняшних публичных Telegram-публикаций нет или файл ещё не создан.</p>'
    return f"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Редакторская очередь — Омск</title>
<style>
:root {{ color-scheme: light; --ink:#1f2937; --muted:#64748b; --line:#dbe2ea; --paper:#f5f7fa; --white:#fff; --link:#0759a5; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--paper); color:var(--ink); font:16px/1.5 "Segoe UI",Arial,sans-serif; }}
header {{ background:var(--white); border-bottom:1px solid var(--line); padding:24px max(16px,calc((100% - 1100px)/2)); }}
main {{ max-width:1100px; margin:0 auto; padding:22px 16px 48px; }}
h1 {{ margin:0 0 4px; font-size:28px; }}
h2 {{ margin:30px 0 12px; font-size:22px; }}
h3 {{ margin:8px 0; font-size:18px; line-height:1.35; }}
p {{ margin:8px 0; }}
.muted {{ color:var(--muted); font-size:13px; }}
.note {{ color:var(--muted); max-width:900px; }}
.stats {{ display:flex; flex-wrap:wrap; gap:10px; margin-top:16px; }}
.stat {{ padding:8px 12px; border:1px solid var(--line); background:var(--white); border-radius:10px; }}
.card {{ padding:16px; margin:12px 0; background:var(--white); border:1px solid var(--line); border-radius:12px; box-shadow:0 1px 2px #0f172a0a; }}
.topline {{ display:flex; flex-wrap:wrap; align-items:center; gap:9px; }}
.rank {{ font-weight:700; }}
.tag {{ display:inline-block; border-radius:5px; padding:2px 8px; background:#edf2f7; color:#334155; font-size:12px; font-weight:600; }}
.bodytext {{ white-space:pre-wrap; overflow-wrap:anywhere; }}
.scores {{ font-size:13px; font-weight:600; }}
.links a {{ display:inline-block; color:var(--link); margin:4px 14px 4px 0; overflow-wrap:anywhere; }}
.tgcard {{ border-left:4px solid #94a3b8; }}
.empty {{ border:1px dashed var(--line); border-radius:10px; padding:18px; color:var(--muted); background:var(--white); }}
footer {{ color:var(--muted); font-size:12px; border-top:1px solid var(--line); padding-top:20px; margin-top:35px; }}
</style>
</head>
<body>
<header>
  <h1>Редакторская очередь — Омск</h1>
  <p class="note">Ссылки ведут на оригинальные публикации. Изображения и видео не скачиваются и не встраиваются.</p>
  <p class="muted">Сформировано: {esc(generated)}</p>
  <div class="stats">
    <div class="stat"><strong>{len(events)}</strong> событий в основной очереди</div>
    <div class="stat"><strong>{len(commercial)}</strong> рекламных / коммерческих публикаций отдельно</div>
    <div class="stat"><strong>{len(telegram)}</strong> Telegram-публикаций для ручной проверки</div>
  </div>
</header>
<main>
  <h2>1. VK + Web Search — очередь с диагностической оценкой</h2>
  <p class="note">Используются существующие фильтр региона, дедупликация и маршрутизатор. Оценки — внутренние модельные баллы, не проценты вероятности вирусности.</p>
  {event_cards}
  <h2>2. Реклама и коммерческие публикации — отдельно</h2>
  <p class="note">Сюда вынесены материалы с явной маркировкой рекламы или сильными коммерческими признаками. Это вспомогательный фильтр: перед окончательным решением список можно просмотреть вручную.</p>
  {commercial_cards}
  <h2>3. Telegram — ссылки для ручной проверки</h2>
  <p class="note">Telegram не участвует в оценке или обучении модели. Список отсортирован по времени публикации; для каждого сообщения дана ссылка на оригинал.</p>
  {telegram_cards}
  <footer>Оперативная редакторская очередь. Не публикует материалы автоматически и не скачивает медиа.</footer>
</main>
</body>
</html>
"""


def main() -> None:
    if not EVENTS_INPUT.exists():
        raise FileNotFoundError(
            f"Не найден {EVENTS_INPUT}. Выполни: "
            "python run_pipeline.py --discovery, затем --events и --route-events."
        )

    events = read_jsonl(EVENTS_INPUT)
    telegram_posts = read_jsonl(TELEGRAM_INPUT, required=False)
    payload = build_payload(events, telegram_posts)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    JSON_OUTPUT.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    HTML_OUTPUT.write_text(render_html(payload), encoding="utf-8")

    print(f"Событий VK/Web: {payload['counts']['vk_web_events']}")
    print(f"Telegram для ручной проверки: {payload['counts']['telegram_manual_posts']}")
    print(f"JSON: {JSON_OUTPUT}")
    print(f"HTML: {HTML_OUTPUT}")


if __name__ == "__main__":
    main()

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

    print(f"Событий в основной VK/Web очереди: {payload['counts']['vk_web_events']}")
    print(f"Реклама/коммерция отдельно: {payload['counts']['commercial_events']}")
    print(f"Всего событий VK/Web: {payload['counts']['vk_web_events_total']}")
    print(f"Telegram для ручной проверки: {payload['counts']['telegram_manual_posts']}")
    print(f"JSON: {JSON_OUTPUT}")
    print(f"HTML: {HTML_OUTPUT}")


if __name__ == "__main__":
    main()
# Архитектура проекта — Discovery: VK + Telegram + Web Search

## 1. Цель
Система должна максимально быстро находить свежие локальные события в Омске и Омской области, объединять одинаковые сообщения из разных источников, оценивать свежесть, скорость распространения и подтверждённость, а затем передавать единый объект новости в Audience Router.

Главный принцип: сначала собираем сигналы, затем нормализуем и объединяем их в события, и только после этого оцениваем вирусность и аудиторию.

## 2. Общая схема

VK Collector ─────┐
Telegram Collector ─┼→ SourcePost → Event Clustering → Freshness/Verification → Scoring → Audience Router → Editorial Queue → Publication → Feedback
Web Search Collector ┘

## 3. Collectors
Collectors отвечают только за получение данных. Они не выбирают лучшую новость и не принимают решение о публикации.

Предлагаемая структура:

collectors/
  vk.py
  telegram.py
  search.py

VK:
- история источников;
- быстрый сбор новых постов;
- нормализация VK-специфичных полей.

Telegram:
- история каналов;
- быстрый сбор новых сообщений;
- обработка изменений и удалений;
- нормализация Telegram-полей.

### 3.1 Web Search

Поисковая выдача является третьим равноправным входом **на уровне discovery**, рядом с VK и Telegram.

Первая реализация использует поисковые RSS-ленты Google News. Поисковый feed поддерживает поисковые запросы, оператор `when:` для ограничения свежести и `site:` для точечного поиска по конкретному издателю. Это позволяет одновременно искать общий поток по Омску и отдельно проверять региональные СМИ. citeturn225889search0turn225889search1

Web Search не считается социальной метрикой и не получает искусственные views/likes/reposts.

Каждый результат сохраняет:
- поисковый запрос;
- время публикации материала;
- название издателя;
- URL издателя, если он доступен в RSS;
- ссылку на найденный материал;
- позицию материала в выдаче;
- список запросов, по которым один и тот же материал был найден.

На уровне событий поиск особенно важен для сценария:

`новостник → Web Search → Telegram/VK`

То есть система может увидеть материал до того, как он разойдётся по соцсетям.

В будущем к этому слою можно добавить отдельные RSS-ленты сайтов и другие поисковые адаптеры без изменения NewsEvent и Scoring.

Telegram предоставляет отдельные Bot API и Telegram API/MTProto. Bot API умеет присылать channel_post и edited_channel_post обновления, но для общего мониторинга публичных каналов и чтения истории архитектурно лучше закладываться на Telegram API/MTProto. Telegram отдельно документирует получение истории и пагинацию сообщений. citeturn990889search0turn487976search2turn487976search5

## 4. Единый формат SourcePost
Оба сборщика должны выдавать один внутренний формат.

Минимальные поля:

source.platform
source.kind
source.source_id
source.source_name
source.source_url
post.id
post.url
post.published_at
post.edited_at
post.text
media.has_media
media.types
media.count
signals.views
signals.likes
signals.comments
signals.reposts
collection.collected_at
collection.collector_version

Отсутствующая метрика должна быть null, а не искусственно превращаться в 0.

## 5. RAW
RAW — неизменяемый слой входных данных.

Поток:

RAW → normalized SourcePost → NewsEvent

Это позволяет менять дедупликацию и scoring без повторного обращения к VK/TG.

## 6. NewsEvent
Одна реальная новость может одновременно появиться в нескольких Telegram-каналах, VK-пабликах и СМИ. Для редакционной системы это должно быть одно событие.

NewsEvent хранит:
- event_id;
- first_seen_at;
- last_seen_at;
- first_source;
- source_count;
- independent_source_count;
- platform_count;
- source_posts;
- canonical_text;
- extracted entities;
- verification state;
- discovery_path.

`first_source` фиксирует, где событие впервые было замечено системой: `vk`, `telegram` или `web_search`.

`discovery_path` нужен для анализа распространения, например:

`web_search → telegram → vk`

или:

`telegram → vk`.

## 7. Дедупликация и кластеризация
На первом этапе без тяжёлой ML-модели.

Каскад:
1. точное совпадение URL, внешнего ID, репоста;
2. нормализация текста;
3. ключевые сущности: место, тип события, объект, числа, имена;
4. текстовая похожесть;
5. временное окно.

Окно и пороги должны зависеть от типа события. ДТП, пожар и политическое заявление не обязательно объединять одинаково.

## 8. Freshness и скорость распространения
Для NewsEvent считаем отдельные признаки:

freshness_age_minutes
spread_minutes
source_velocity
platform_velocity
first_seen_at
last_seen_at
search_first_seen
social_first_seen
web_to_social_minutes

Это отдельный слой. Не смешиваем его напрямую с историческим POTENTIAL.

Отдельно измеряем, сколько времени прошло от первого появления в Web Search до первого появления в VK/TG. Такой сигнал нужен не для доказательства причинности, а для оценки опережающих источников.

## 9. Verification
Три уровня:

UNVERIFIED
SECONDARY_CONFIRMED
PRIMARY_CONFIRMED

Первичный источник — официальное ведомство или другой первичный источник факта. Вторичный — надёжное региональное СМИ. Один локальный канал без подтверждения — сигнал, но не подтверждение.

Отсутствие подтверждения не означает ложность. Оно означает повышенный редакционный риск.

## 10. Event Strength
Существующий event_strength сохраняем.

Новая формула должна учитывать не только сам текст, но и контекст события:

event_strength
+ freshness
+ verification
+ source velocity
+ number of independent sources

Количество источников должно иметь насыщение: переход от 1 к 2 источникам важнее, чем от 15 к 16.

## 11. Audience Router
Router получает NewsEvent, а не набор разрозненных постов.

Он использует:

event_strength
freshness
verification
source_count
platform_count
historical score Golos
historical score Zhest
audience_fit Golos
audience_fit Zhest
affinity

И возвращает три разных понятия:

recommended_target — куда отправлять новость;
secondary_candidate — альтернативная площадка;
confidence — насколько решение устойчиво.

Важно: PRIMARY/SECONDARY не должны означать автоматическую публикацию. Это рекомендации маршрутизатора.

## 12. Publication
Публикация отделена от scoring:

scoring → routing → editorial queue → publisher

Позже можно подключить независимые адаптеры:

VK Publisher
Telegram Publisher
MAX Publisher

## 13. Feedback Loop
После публикации сохраняем:

event_id
recommended_target
editor_decision
actual_target
post_id
published_at
views
likes
comments
reposts
result_percentile

Это позволит различать:

model error
editor override
publication mismatch

## 14. Две скорости
FAST PATH:

VK/TG/Web Search → новые публикации → normalize → dedup → NewsEvent → score → queue

Web Search не заменяет VK/TG: он даёт ранний сигнал и возможный первичный материал СМИ, после чего событие объединяется с последующими соцпубликациями.

DEEP PATH:

RAW history → dataset → analytics → OOS → models → calibration

Fast path не должен каждый запуск пересобирать историю и модели.

## 15. Структура проекта

collectors/
  vk.py
  telegram.py
  search.py

normalization/
  source_post.py

events/
  clustering.py
  freshness.py
  verification.py

scoring/
  event_score.py
  news_score.py

routing/
  audience_router.py

feedback/
  publication_feedback.py

scripts/
  00_smoke_test.py
  01_collect.py
  02_build_dataset.py
  03_analyze_audience.py
  04_build_editorial_model.py
  05_score_news.py
  06_publish_github.py

data/
  raw/vk/
  raw/telegram/
  raw/search/
  normalized/
  events/
  dataset/
  analytics/
  model/
  scoring/
  feedback/

## 15.1 Текущее состояние реализации

На ветке `audience-router` discovery-слой теперь внедряется поверх старого pipeline без миграции scoring.

Уже есть:

- `collectors/search.py` — Web Search через Google News RSS;
- `collectors/vk.py` — VK → нормализованный `SourcePost`;
- `collectors/telegram.py` — опциональный MTProto-адаптер с локальной сессией;
- `normalization/source_post.py` — единый формат;
- `scripts/01_collect_discovery.py` — сбор VK + Telegram + Web Search в `data/normalized/source_posts.jsonl`.

Старый `scripts/01_collect_vk.py` намеренно не заменён: его RAW-схема остаётся совместимой с текущим dataset/scoring.

Для проверки нового слоя:

```bash
python run_pipeline.py --discovery
```

Эта команда не пересобирает dataset, модели или scoring.

Telegram по умолчанию выключен. Для него нужны локальные `TELEGRAM_API_ID`, `TELEGRAM_API_HASH` и session; credentials не должны попадать в Git.

## 16. Приоритет реализации
Этап A — VK, Telegram и Web Search collectors.
Этап B — единый SourcePost для всех discovery-источников.
Этап C — Event clustering с cross-platform dedup.
Этап D — Freshness и source velocity.
Этап E — Verification.
Этап F — подключение Event к текущему Audience Router.
Этап G — Feedback + Publication Tracker.
Этап H — OOS всего контура.
Этап I — ML после накопления реального feedback.

## 17. Главный принцип
Мы не строим два отдельных парсера, которые напрямую кормят scoring.

Мы строим единую цепочку:

VK ─────────────┐
Telegram ───────┼→ SourcePost → NewsEvent → scoring → routing → publication → feedback
Web Search ─────┘

Так новая площадка добавляется как новый collector, а не как второй независимый проект.
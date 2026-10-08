# Анализатор контента — Omsk / VK + Telegram + Web Search / две VK-аудитории

Проект анализирует исторические публикации двух VK-сообществ и строит две независимые редакторские модели.

Текущая версия ветки: **refactor/performance 3.1**.

- `golos` — **Голос Омска**
- `zhest` — **Новости Омска | Жесть**

Главная идея: **один общий аналитический движок + отдельные Audience Profiles и модели для каждой аудитории**.

---

# 0. Первый запуск после клонирования

Установить зависимости:

```bash
python -m pip install -r requirements.txt
```

Проверить окружение и ключевые артефакты:

```bash
python scripts/00_smoke_test.py
```

## 1. Что делает pipeline

### Этап 01 — discovery-сбор

Источники постепенно собираются в общий discovery-слой:

```text
VK
Telegram
Web Search
   ↓
SourcePost
   ↓
NewsEvent
```

На текущем этапе в pipeline уже подключены VK и Web Search. Telegram-collector остаётся следующим этапом интеграции MTProto.

```text
scripts/01_collect_vk.py
```

Получает историю постов обеих групп через VK API и сохраняет:

```text
data/raw/omsk_vk_raw.json
```

Web Search:

```text
data/raw/search/omsk_search_raw.json
```

Результаты поиска используются как discovery-сигналы и сохраняются отдельно от исторического VK dataset, пока не завершён слой NewsEvent.

По умолчанию собирается до 2000 постов на каждую группу.

Запуск:

```bash
python scripts/01_collect_vk.py
```

или общий discovery-сбор:

```bash
python run_pipeline.py --collect
```

Он обновляет VK RAW и поисковую выдачу.

Только Web Search:

```bash
python run_pipeline.py --search-only
```

Единый нормализованный discovery-слой:

```bash
python run_pipeline.py --discovery
```

Он собирает:

```text
VK + Telegram* + Web Search
        ↓
     SourcePost
        ↓
data/normalized/source_posts.jsonl
```

`*` Telegram подключается только при включённом `TELEGRAM_ENABLED` и настроенных локальных MTProto credentials. Исторический VK RAW, dataset, модели и scoring этим режимом не изменяются.


---

### Этап 02 — dataset

```text
scripts/02_build_dataset.py
```

Из общего RAW строится единый dataset.

Для каждого поста определяется:

```text
audience = golos / zhest
```

Добавляются:

- like rate
- comment rate
- repost rate
- engagement rate
- views per hour
- percentiles
- VIRALITY
- APPROVAL
- POTENTIAL
- metric confidence
- confidence-adjusted potential
- content type
- mechanisms

Результаты:

```text
data/dataset/omsk_vk_dataset.json
data/dataset/omsk_vk_dataset.csv
```

---

## 3. Историческая модель

### Этап 03

```text
scripts/03_analyze_audience.py
```

Для каждой аудитории отдельно строятся:

- content types
- mechanisms
- пары механизмов
- тройки механизмов
- стабильность комбинаций
- chronological OOS validation
- top virality
- top approval
- top potential
- Audience Profile

Результаты:

```text
data/analytics/audience_report.json
data/model/audience_profiles.json
```

---

## 4. Отдельные модели

### Этап 04

```text
scripts/04_build_editorial_model.py
```

Строит:

```text
models.golos
models.zhest
```

Комбинационные бонусы разрешаются только из chronological OOS-валидации.

Это важно:

> Хорошая комбинация на всей исторической выборке ещё не означает, что она будет работать в будущем.

Поэтому комбинация получает право влиять на fresh score только после проверки на следующих временных периодах.

Результаты:

```text
data/model/editorial_model.json

data/model/golos/editorial_model.json
data/model/zhest/editorial_model.json

data/analytics/golos/audience_report.json
data/analytics/zhest/audience_report.json
```

---

# 5. Audience Separator

### Этап 05

```text
scripts/05_score_news.py
```

Каждая свежая новость прогоняется через **обе** модели.

Например:

```text
Новость
   ↓
┌───────────────┐
│ model_golos   │ → score_golos
└───────────────┘
        +
┌───────────────┐
│ model_zhest   │ → score_zhest
└───────────────┘
```

Но:

## Raw score НЕ сравнивается напрямую

Например:

```text
Golos = 63
Zhest = 57
```

это ещё не означает, что Golos лучше.

У аудиторий разные исторические шкалы.

Поэтому строится:

```text
audience_fit.golos
audience_fit.zhest
```

Это percentile свежего score внутри исторического распределения **соответствующей аудитории**.

Например:

```text
Golos:
score = 63
fit   = 78

Zhest:
score = 57
fit   = 82
```

В таком случае новость лучше подходит Жести, несмотря на меньший raw score.

---

# 6. Диагностический routing

Сейчас используется:

```text
fit < 55
    ↓
SKIP_OR_EDITORIAL_REVIEW

разница <= 5
    ↓
BOTH

разница 5–12
    ↓
PRIMARY + SECONDARY

разница > 12
    ↓
ONLY
```

Например:

```text
Golos fit = 84
Zhest fit = 81

margin = 3

→ BOTH
```

И:

```text
Golos fit = 91
Zhest fit = 67

margin = 24

→ golos_ONLY
```

Но это пока **DIAGNOSTIC_ONLY**.

Production-публикация автоматически не меняется.

---

# 7. Почему две модели, а не одна

Паблики имеют разные аудитории.

### Голос Омска

Более широкая аудитория:

- городские новости
- полезность
- транспорт
- изменения в городе
- события
- необычные истории
- бытовые темы
- положительные новости

### Жесть

Более выраженная hard-news аудитория:

- ДТП
- погибшие
- пострадавшие
- происшествия
- опасность
- конфликты
- шок
- сильные визуальные поводы
- просьбы о помощи

Но это **гипотеза**, которую система должна проверять на данных.

Поэтому не зашиваем:

```text
ДТП → Жесть
```

а измеряем:

```text
ДТП → насколько хорошо исторически
       работает в Golos

ДТП → насколько хорошо исторически
       работает в Zhest
```

---

# 8. Важная архитектурная идея

Не создаются два разных аналитических движка.

Есть:

```text
                 ОБЩИЙ ENGINE
                     │
          ┌──────────┴──────────┐
          ↓                     ↓
      GOLOS PROFILE         ZHEST PROFILE
          ↓                     ↓
      GOLOS MODEL           ZHEST MODEL
          ↓                     ↓
          └──────────┬──────────┘
                     ↓
              AUDIENCE SEPARATOR
```

Это позволяет постепенно добавлять:

- новые паблики
- новые аудитории
- новые механизмы
- новые модели
- ML-калибровку

без переписывания всей системы.

---

# 9. Полный запуск

Если RAW уже есть:

```bash
python run_pipeline.py
```

Он выполняет:

```text
02 → 03 → 04 → 05
```

Если нужно сначала заново собрать историю VK:

```bash
python run_pipeline.py --collect
```

Тогда:

```text
01 → 02 → 03 → 04 → 05
```

---

# 10. Fresh news

Файл:

```text
data/scoring/fresh_news.json
```

может содержать массив:

```json
[
  {
    "title": "Заголовок новости",
    "text": "Текст новости",
    "verified": true
  }
]
```

или объект с:

```json
{
  "posts": [...]
}
```

После обработки:

```text
data/scoring/scored_news.json
```

Внутри будут:

```text
audience_scores
audience_fit
audience_mechanism_fit
audience_routing
editorial_score_absolute
editorial_status
editorial_rank
```

---

# 11. Что означает score

Исторические метрики:

```text
VIRALITY
    60% repost rate percentile
    25% engagement percentile
    15% views velocity percentile

APPROVAL
    75% like rate percentile
    25% engagement percentile

POTENTIAL
    60% VIRALITY
    40% APPROVAL
```

Комментарии не считаются положительной реакцией автоматически.

Они остаются отдельным discussion signal.

---

# 12. Fresh event signal

Историческая модель не должна полностью игнорировать масштаб свежего события.

Поэтому есть отдельный `fresh_event_strength`.

Он учитывает, например:

- число погибших
- пострадавших
- тяжесть состояния
- ребёнок + ДТП
- карантин + заболевание
- экологическую угрозу
- пожар
- подтверждённость

Это ограниченный редакторский слой.

Он не заменяет историческую модель.

---

# 13. Animal classifier

Для `animal` используются отдельные регулярные выражения.

Это сделано потому, что простая проверка:

```python
"кот" in text
```

создаёт много ложных срабатываний.

Например, обычные русские слова могут случайно содержать похожие последовательности букв.

---

# 14. Безопасность ключей

Ключи не входят в рабочий проект.

VK:

```text
secrets/vk_service_key.txt
```

или:

```text
VK_SERVICE_KEY
```

GitHub:

```text
secrets/github_token.txt
```

или:

```text
GITHUB_TOKEN
```

Для GitHub также:

```text
GITHUB_OWNER
GITHUB_REPO
GITHUB_BRANCH
```

`GITHUB_BRANCH` по умолчанию:

```text
audience-router
```

---

# 15. GitHub публикация

Это отдельный необязательный этап:

```bash
python scripts/06_publish_github.py
```

Он требует настройки GitHub.

Pipeline `run_pipeline.py` автоматически его не запускает.

---

# 16. Следующий этап развития

После того как эта версия стабильно отработает на нескольких свежих выборках, следующий шаг:

```text
Audience Separator OOS
```

То есть проверять не только:

```text
какой fit сегодня выше
```

но и:

```text
если бы мы принимали решение
в прошлом,

какой паблик реально оказался
лучше через следующие часы/сутки?
```

Только после этого можно включать production routing.

Следующий уровень:

```text
historical analytics
        ↓
OOS validation
        ↓
Audience Separator
        ↓
prediction vs actual result
        ↓
calibration
        ↓
ML
```

ML имеет смысл добавлять только после накопления такой обратной связи.


---

# 17. Рефакторинг и производительность

В ветке `audience-router` аналитическое ядро оптимизировано без смены основной формулы scoring:

- percentile для исторических метрик теперь сортируется один раз на метрику и использует бинарный поиск;
- комбинации механизмов агрегируются потоково через суммы и счётчики вместо хранения копий score-строк;
- регулярные выражения классификатора компилируются один раз;
- одна свежая новость классифицируется один раз и затем используется обеими моделями;
- исторический `model score` для Audience Profile теперь не пересчитывается дважды;
- индекс механизмов модели кэшируется в памяти процесса;
- в chronological OOS устранён повторный расчёт одного и того же списка комбинаций;
- добавлен `--score-only`, чтобы ежедневная оценка fresh news не запускала тяжёлую перестройку истории.

Логика и thresholds не должны автоматически считаться улучшенными только потому, что код стал быстрее. После `git pull` текущие результаты нужно сравнить с предыдущим прогоном на тех же входных данных.

# 18. Git workflow проекта

Эта ветка предназначена только для проекта Audience Router.

Для discovery-слоя сейчас действует принцип:

```text
VK ─────────────┐
Telegram ───────┼→ SourcePost → NewsEvent
Web Search ─────┘
                     ↓
                 Scoring
                     ↓
              Audience Router
```

Web Search не получает искусственные социальные метрики. Его ценность — в раннем обнаружении материала новостников, поисковой выдаче и последующем объединении с VK/TG-публикациями.

`main` в репозитории используется другим проектом и не является источником истины для этого кода.

Команды:

```bash
git pull
git status
python run_pipeline.py --score-only
```

Полная перестройка:

```bash
python run_pipeline.py
```

Обновление истории VK:

```bash
python run_pipeline.py --collect
```

Секреты хранятся только локально в `secrets/` и исключены из Git.

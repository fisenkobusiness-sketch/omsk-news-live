# Архитектура проекта

## Принципы

- Одна точка запуска: `run_smm_poiskovik.py`.
- Единственная копия прикладной логики — в `src/`.
- В корне нет совместимых копий рабочих модулей: запускать отдельные этапы вручную для обычной работы не нужно.
- Генерируемые очереди, SQLite и логи хранятся в `runtime/`, который исключён из Git.
- Секреты хранятся в `.secrets/`, который исключён из Git.
- `editorial_pool.json` остаётся в корне, поскольку монитор публикует его как актуальный пул кандидатов.
- `PUBLISHED_TOPICS.json` остаётся в корне как постоянный реестр истории публикаций.

## Компоненты

| Путь | Назначение |
|---|---|
| `run_smm_poiskovik.py` | Единый запуск монитора и трекера |
| `src/live_monitor.py` | Сбор VK-постов, вызов этапов анализа, публикация пула |
| `src/analysis.py` | Первичная классификация и жёсткие редакционные фильтры |
| `src/predictor.py` | Итоговый рейтинг `editorial_v2` |
| `src/metrics.py` | Общие функции расчёта метрик |
| `src/smm_poiskovik_engagement_tracker.py` | Независимый трекер вовлечённости |
| `tools/diagnostic.py` | Read-only диагностика очередей |
| `tools/check_smm_poiskovik_connections.py` | Read-only проверка доступности VK и Telegram |
| `tests/` | Регрессионные тесты |
| `docs/` | Техническая документация |
| `runtime/` | Игнорируемые Git временные данные и очереди |

## Контракт рейтинга

- Единственный итоговый рейтинг — `prediction.priority_score` (0–100).
- Версия модели в каждой оценке — `prediction.score_version = editorial_v2`.
- `score`, `viral_score` и `editorial_score` — диагностические поля старого анализатора, не самостоятельный итоговый рейтинг.
- Отсутствующие показатели не трактуются как нулевой интерес.
- Запрещённые темы, реклама и промо остаются жёсткими исключениями.
- Уверенность относится к проверке фактов и не повышает популярность материала.

## Проверка

```powershell
python -m py_compile run_smm_poiskovik.py src\live_monitor.py src\analysis.py src\predictor.py src\metrics.py src\smm_poiskovik_engagement_tracker.py tools\diagnostic.py tools\check_smm_poiskovik_connections.py
python -m unittest discover -s tests -p "test_*.py" -v
```

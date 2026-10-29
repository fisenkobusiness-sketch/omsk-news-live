# СММ Поисковик — новости Омска

Единая точка запуска проекта — `run_smm_poiskovik.py`. Рабочая логика находится в `src/`; отдельные копии модулей в корне не используются.

## Запуск

1. Откройте проект в PyCharm и активируйте виртуальное окружение.
2. Установите зависимость, если это новая среда: `python -m pip install requests`.
3. Проверьте локальные секреты в `.secrets/`:
   - `vk_service_key.txt`
   - `github_token.txt`
   - секреты Telegram, если используете уведомления трекера.
4. Запустите `run_smm_poiskovik.py`.

Запускатель согласованно запускает монитор VK и трекер вовлечённости. Для остановки нажмите `Ctrl+C`. Не запускайте параллельно второй экземпляр комбайна.

## Структура

- `run_smm_poiskovik.py` — единственная рекомендуемая точка запуска.
- `src/live_monitor.py` — сбор свежих публикаций VK и публикация пула.
- `src/analysis.py` — первичная классификация и редакционные фильтры.
- `src/predictor.py` — итоговый рейтинг `editorial_v2`; канонический рейтинг — `prediction.priority_score`.
- `src/metrics.py` — общие расчёты метрик.
- `src/editorial_rules.py` — единые жёсткие фильтры и удаление устаревших флагов из runtime-данных.
- `src/smm_poiskovik_engagement_tracker.py` — отдельное измерение динамики вовлечённости.
- `tools/diagnostic.py` — диагностика очередей без изменения файлов.
- `tools/check_smm_poiskovik_connections.py` — проверка подключений VK/Telegram без запуска монитора.
- `tests/` — автоматические проверки.
- `docs/` — техническая документация.
- `runtime/` — временные очереди, состояние, база трекера и логи; эти данные не коммитятся.
- `.secrets/` — локальные секреты; эта папка не коммитится.

## Поток данных

`VK → runtime/vk_today.json → src/analysis.py → runtime/editor_queue.json → src/predictor.py → runtime/predictor_queue.json → editorial_pool.json`

`editorial_pool.json` остаётся в корне намеренно: монитор публикует этот файл как текущий пул кандидатов. `PUBLISHED_TOPICS.json` — отдельный постоянный реестр редакционной истории.

## Проверка после изменений

```powershell
python -m py_compile run_smm_poiskovik.py src\live_monitor.py src\analysis.py src\predictor.py src\metrics.py src\smm_poiskovik_engagement_tracker.py tools\diagnostic.py tools\check_smm_poiskovik_connections.py
python -m unittest discover -s tests -p "test_*.py" -v
```

Не редактируйте `editorial_pool.json` вручную: это генерируемый результат.

# СММ Поисковик — новости Омска

Основной код конвейера находится в `src/`. Корневые файлы `analysis.py`, `predictor.py`, `live_monitor.py` и `metrics.py` оставлены только для совместимости со старыми командами: отдельной логики в них больше нет.

## Запуск

1. Откройте проект в PyCharm и активируйте виртуальное окружение.
2. Установите зависимости, если это новая среда: `python -m pip install requests`.
3. Проверьте локальные секреты в `.secrets/`:
   - `vk_service_key.txt`
   - `github_token.txt`
4. Запустите **только** `run_smm_poiskovik.py`.

Запускатель поднимает монитор VK и трекер вовлечённости. Для остановки нажмите `Ctrl+C`. Не запускайте одновременно корневые скрипты и запускатель.

## Структура

- `run_smm_poiskovik.py` — единственная рекомендуемая точка запуска.
- `src/live_monitor.py` — сбор свежих публикаций VK, управление циклами и обновление `editorial_pool.json`.
- `src/analysis.py` — классификация, фильтры и первичный анализ тем.
- `src/predictor.py` — единая модель `editorial_v2`; канонический рейтинг: `prediction.priority_score`.
- `src/metrics.py` — общие расчёты охвата и вовлечённости.
- `src/smm_poiskovik_engagement_tracker.py` — независимое измерение динамики вовлечённости.
- `runtime/` — временные очереди, состояние и логи; не коммитить эти данные.
- `tools/diagnostic.py` — диагностика очередей без изменения файлов.
- `tests/` — автоматические проверки.

## Путь данных

`VK → runtime/vk_today.json → src/analysis.py → runtime/editor_queue.json → src/predictor.py → runtime/predictor_queue.json → editorial_pool.json`

Публикация в GitHub выполняется монитором после успешной сборки очереди. Перед реальной публикацией новостей отдельно проверяйте факты и источники: рейтинг помогает расставлять приоритеты, но не заменяет редакторскую проверку.

## Проверка после изменений

```powershell
python -m py_compile run_smm_poiskovik.py src\live_monitor.py src\analysis.py src\predictor.py src\metrics.py
python -m unittest discover -s tests -p "test_*.py" -v
```

Не редактируйте `editorial_pool.json` вручную: это генерируемый результат.

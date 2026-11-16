# AeroPulse — задержки рейсов аэропорта Chicago O'Hare (ORD)

Проектная работа по дисциплине «Визуализация данных» (НИТУ МИСИС), тема №7 «Гражданская авиация»:
прогноз числа рейсов и доли задержек в аэропорту.

**Команда:** Харлашкина А.В., Селиванова А.К., Козлов В.Н.

## Части проекта

| Часть | Ответственный | Код | Страница дашборда |
|---|---|---|---|
| A. Задержки: сбор BTS, журнал загрузок, инкрементальность, устойчивость, качество данных, редактирование | Харлашкина А.В. | `pipeline.py`, `sources/bts.py`, `dq.py`, `edits.py` | «Данные», «Журнал и качество» |
| B. Погода: METAR (слабоструктурированные данные), прогноз Open-Meteo, связь погоды и задержек | Селиванова А.К. | `sources/metar.py`, `sources/openmeteo.py`, `metar_parser.py`, `ui.py` | «Погода и задержки» |
| C. Прогноз: витрина, модель, оценка точности, прогноз на 7 дней | Козлов В.Н. | `marts.py`, `model.py` | «Прогноз» |

## Запуск

```bat
run.bat                  :: первый запуск: окружение + загрузка истории (~35 мин) + дашборд
update.bat               :: только обновить данные
schedule_install.bat     :: обновлять каждый час через Планировщик заданий Windows
```

Вручную:
```bat
.venv\Scripts\python pipeline.py                       :: вся цепочка
.venv\Scripts\python pipeline.py --only bts metar      :: отдельные шаги
.venv\Scripts\python -m streamlit run app.py           :: дашборд
.venv\Scripts\python -m pytest                         :: тесты (48)
set AERO_FAULT=rate_limit_429 & .venv\Scripts\python pipeline.py --only openmeteo   :: демо сбоя
```

Аэропорт, координаты и глубина истории задаются в `config.py` или переменными окружения `AERO_*`.

## Документация

| Файл | О чём |
|---|---|
| [docs/sources.md](docs/sources.md) | источники: URL, форматы, лимиты, проверка |
| [docs/architecture.md](docs/architecture.md) | схема системы, автоматизация, обоснование стека |
| [docs/data-model.md](docs/data-model.md) | таблицы и связи |
| [docs/dq.md](docs/dq.md) | правила качества и что они нашли |
| [docs/model.md](docs/model.md) | модель, признаки, проверка, метрики, ограничения |
| [docs/dashboard-questions.md](docs/dashboard-questions.md) | вопрос пользователя → виджет → решение |
| [docs/report-notes.md](docs/report-notes.md) | заготовки разделов отчёта по участникам |
| [docs/demo-script.md](docs/demo-script.md) | сценарий защиты по ролям и частые вопросы |

**Развернуть у себя и подготовиться к защите — [SETUP.md](SETUP.md).**

Отчёт и презентация: `report/Отчет_Визуализация_данных_AeroPulse.docx`, `report/Презентация_AeroPulse.pptx` (в заметках к слайдам — кто что говорит). Пересборка: `report/build_report.py`, `report/build_deck.py` (зависимости — `report/requirements.txt`).

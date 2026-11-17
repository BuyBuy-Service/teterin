# Источники данных (проверено 16.11.2026 реальными запросами)

| # | Источник | Формат | Тип | Кто отвечает |
|---|---|---|---|---|
| S1 | BTS On-Time Performance | ZIP с CSV, помесячно | структурированный, пакетный | A |
| S2 | METAR через Iowa Environmental Mesonet: ORD + 10 аэропортов сети | CSV, внутри — сырой текст METAR | **слабоструктурированный** (текст + показания датчиков) | B |
| S3 | Open-Meteo Forecast | JSON | структурированный, API | B (используется в прогнозе C) |

## S1. BTS — рейсы и задержки

- URL: `https://transtats.bts.gov/PREZIP/On_Time_Reporting_Carrier_On_Time_Performance_1987_present_{YYYY}_{M}.zip` (месяц без ведущего нуля).
- Без ключа. Нет месяца → HTTP 404 (тело — HTML-страница).
- **Последний доступный месяц на 16.11.2026: август 2026** (`Last-Modified: 26 Oct 2026`). Лаг публикации ≈ 2–3 месяца.
- Размер: ~32 МБ ZIP, ~608 тыс. строк по всем США за месяц; скачивание ~75 с.
- Для ORD: ~66 тыс. строк в месяц (вылеты + прилёты), ~33 тыс. вылетов (≈1070 в день).
- В ZIP: `On_Time_Reporting_..._{YYYY}_{M}.csv` + `readme.html`. 110 колонок, последняя пустая (`Unnamed: 109`).
- Используемые колонки: `FlightDate, Reporting_Airline, Flight_Number_Reporting_Airline, Tail_Number, Origin, Dest, CRSDepTime, DepTime, DepDelay, DepDel15, CRSArrTime, ArrTime, ArrDelay, ArrDel15, Cancelled, CancellationCode, Diverted, CarrierDelay, WeatherDelay, NASDelay, SecurityDelay, LateAircraftDelay`.
- Время — местное время аэропорта в формате `hhmm` (бывает `2400`).
- Задержка: `DepDel15 = 1`, если вылет задержан ≥ 15 мин (стандарт DOT). Минуты по причинам заполнены только при задержке прибытия ≥ 15 мин.

## S2. METAR (IEM ASOS)

- URL: `https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py`
- Параметры: `station=ORD&data=metar&tz=Etc/UTC&format=onlycomma&latlon=no&report_type=3&report_type=4&year1..day2`.
- **Конечная дата `day2` не включается** (запрос 14→15 вернул только 14-е).
- Ответ: CSV `station,valid,metar`, где `metar` — сырой текст, например
  `KORD 140251Z 33013G20KT 10SM FEW050 02/M04 A3010 RMK AO2 SLP200 T00221039 51006`.
- Регулярные сводки ежечасно в :51, плюс внеочередные (SPECI) при изменении погоды.
- Без ключа; ограничение по IP, под нагрузкой отдаёт 503 → ретраи с паузой, запросы по ≤ 1 месяцу.
- Ответ на сутки — ~1 с.

## S3. Open-Meteo Forecast

- URL: `https://api.open-meteo.com/v1/forecast?latitude=41.9786&longitude=-87.9048&timezone=UTC&forecast_days=7&hourly=...`
- Поля: `temperature_2m, precipitation, snowfall, wind_speed_10m, wind_gusts_10m, visibility, cloud_cover, weather_code`.
- 168 часов (7 дней), начиная с 00:00 UTC текущих суток. Без ключа (некоммерческое использование).
- Ограничение: нет высоты нижней границы облаков, поэтому категорию IFR для прогноза оцениваем только по видимости. Это расходится с METAR, нужно учесть при согласовании признаков модели.

## Отклонения от исходного ТЗ

- Источники FAA NAS Status и OpenSky не используются: команда упростила проект до трёх источников.
- Сырой BTS хранится файлами (ZIP + sha256 в `raw_files`). Построчную копию в БД не храним: файл и так неизменяем и полностью воспроизводит данные.

## Сеть аэропортов (добавлено 17.11.2026)

Погода в аэропортах назначения влияет на задержки вылетов из ORD (рейсы держат на земле, пока не освободится
аэропорт прибытия). Взяты 10 направлений с наибольшим числом рейсов из ORD (по BTS, ~21% вылетов):
LGA, BOS, LAX, DFW, DCA, MSP, DEN, ATL, EWR, DTW. Список и координаты — `config.NETWORK`.

- METAR для них — тот же IEM: параметр `station` можно повторить, все станции приходят одним ответом
  (отдельный шаг `metar_network` со своей отметкой загрузки).
- Прогноз — тот же Open-Meteo: `latitude`/`longitude` принимают списки через запятую, ответ — JSON-массив
  в том же порядке. В `forecast_weather` добавлена колонка `station`.

## История — 4 года (с 09.2022)

Двух лет мало: редкие явления (ледяной дождь, метели) встречаются считанные разы. 2020–2021 не берём —
пандемийный провал трафика. Глубина — `config.BACKFILL_MONTHS = 48`; загрузка сама догружает недостающие
месяцы BTS и METAR раньше самой ранней сводки, если историю удлинили.

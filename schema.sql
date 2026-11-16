-- AeroPulse: схема SQLite. Все CREATE идемпотентны.
-- Слои: raw_* (как пришло из источника) -> flights / weather_obs / forecast_weather (очищено)
--       -> daily (витрина) -> predictions (прогноз). Служебное: load_log, watermarks, dq_log, edit_log.

-- ===== Служебное =====
CREATE TABLE IF NOT EXISTS load_log (            -- журнал загрузок: одна строка = один запуск джобы
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    job           TEXT NOT NULL,                 -- bts / metar / openmeteo / transform / model ...
    params        TEXT,                          -- JSON параметров запуска
    trigger       TEXT NOT NULL DEFAULT 'manual',-- manual / schedule / backfill
    started_at    TEXT NOT NULL,
    finished_at   TEXT,
    status        TEXT NOT NULL DEFAULT 'running', -- running / success / partial / failed / skipped
    rows_fetched  INTEGER DEFAULT 0,
    rows_inserted INTEGER DEFAULT 0,
    rows_updated  INTEGER DEFAULT 0,
    rows_skipped  INTEGER DEFAULT 0,             -- дубли и защищённые ручные правки
    http_calls    INTEGER DEFAULT 0,
    retries       INTEGER DEFAULT 0,
    watermark_before TEXT,
    watermark_after  TEXT,
    error         TEXT
);

CREATE TABLE IF NOT EXISTS watermarks (          -- докуда загружен каждый источник
    source     TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS dq_log (              -- результаты проверок качества
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id     INTEGER REFERENCES load_log(id),
    rule       TEXT NOT NULL,
    severity   TEXT NOT NULL,                    -- error / warning
    checked    INTEGER NOT NULL,
    failed     INTEGER NOT NULL,
    sample     TEXT,                             -- примеры проблемных ключей
    checked_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS edit_log (            -- аудит ручных правок из UI
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         TEXT NOT NULL,
    user_name  TEXT NOT NULL,
    table_name TEXT NOT NULL,
    row_key    TEXT NOT NULL,
    field      TEXT NOT NULL,
    old_value  TEXT,
    new_value  TEXT
);

-- ===== Raw =====
CREATE TABLE IF NOT EXISTS raw_files (           -- скачанные ZIP BTS (сам файл лежит в data/raw/bts)
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    source     TEXT NOT NULL,
    period     TEXT NOT NULL,                    -- YYYY-MM
    url        TEXT,
    sha256     TEXT NOT NULL,
    size       INTEGER,
    path       TEXT NOT NULL,
    loaded_at  TEXT NOT NULL,
    UNIQUE (source, sha256)
);

CREATE TABLE IF NOT EXISTS raw_metar (           -- сырые METAR-сводки, как текст
    station         TEXT NOT NULL,
    observed_at_utc TEXT NOT NULL,
    raw_text        TEXT NOT NULL,
    fetched_at      TEXT NOT NULL,
    PRIMARY KEY (station, observed_at_utc, raw_text)
);

CREATE TABLE IF NOT EXISTS raw_forecast (        -- сырые JSON-ответы Open-Meteo
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    fetched_at   TEXT NOT NULL,
    sha256       TEXT NOT NULL UNIQUE,
    payload_json TEXT NOT NULL
);

-- ===== Очищенные данные =====
CREATE TABLE IF NOT EXISTS flights (             -- рейсы ORD (вылеты и прилёты) из BTS
    flight_date     TEXT NOT NULL,               -- местная дата
    carrier         TEXT NOT NULL,
    flight_number   INTEGER NOT NULL,
    origin          TEXT NOT NULL,
    dest            TEXT NOT NULL,
    crs_dep_time    INTEGER NOT NULL,            -- hhmm, местное время
    direction       TEXT NOT NULL,               -- departure / arrival (относительно аэропорта)
    dep_time        INTEGER,
    dep_delay       REAL,
    dep_del15       INTEGER,
    crs_arr_time    INTEGER,
    arr_time        INTEGER,
    arr_delay       REAL,
    arr_del15       INTEGER,
    cancelled       INTEGER NOT NULL DEFAULT 0,
    cancellation_code TEXT,
    diverted        INTEGER NOT NULL DEFAULT 0,
    carrier_delay   REAL,
    weather_delay   REAL,
    nas_delay       REAL,
    security_delay  REAL,
    late_aircraft_delay REAL,
    tail_number     TEXT,
    file_id         INTEGER REFERENCES raw_files(id),
    is_manual       INTEGER NOT NULL DEFAULT 0,  -- 1 = правили вручную, повторная загрузка не перезапишет
    is_deleted      INTEGER NOT NULL DEFAULT 0,  -- мягкое удаление
    updated_at      TEXT NOT NULL,
    PRIMARY KEY (flight_date, carrier, flight_number, origin, dest, crs_dep_time)
);
CREATE INDEX IF NOT EXISTS ix_flights_date ON flights(flight_date, direction);

CREATE TABLE IF NOT EXISTS weather_obs (         -- распарсенный METAR
    station         TEXT NOT NULL,
    observed_at_utc TEXT NOT NULL,
    raw_text        TEXT NOT NULL,
    temp_c          REAL,
    wind_kt         REAL,
    gust_kt         REAL,
    vis_sm          REAL,                        -- видимость, мили
    ceiling_ft      REAL,                        -- нижняя граница BKN/OVC/VV
    precip          INTEGER, rain INTEGER, snow INTEGER, fzra INTEGER,
    ts              INTEGER, fog INTEGER, mist INTEGER,
    flight_cat      TEXT,                        -- VFR / MVFR / IFR / LIFR
    parse_ok        INTEGER NOT NULL,
    PRIMARY KEY (station, observed_at_utc)
);

CREATE TABLE IF NOT EXISTS forecast_weather (    -- последний почасовой прогноз Open-Meteo
    time_utc      TEXT PRIMARY KEY,
    fetched_at    TEXT NOT NULL,
    temp_c        REAL, precip_mm REAL, snow_cm REAL,
    wind_kt       REAL, gust_kt REAL, vis_sm REAL,
    cloud_cover   REAL, weather_code INTEGER
);

-- ===== Витрина и прогноз =====
CREATE TABLE IF NOT EXISTS daily (               -- день x аэропорт: факт рейсов + погода
    date            TEXT PRIMARY KEY,
    dep_scheduled   INTEGER, dep_flown INTEGER, dep_cancelled INTEGER,
    dep_del15_share REAL,                        -- доля вылетов с задержкой >= 15 мин
    dep_delay_mean  REAL,
    arr_flown       INTEGER, arr_del15_share REAL,
    min_carrier REAL, min_weather REAL, min_nas REAL, min_security REAL, min_late_aircraft REAL,
    w_min_vis REAL, w_max_gust REAL, w_ifr_hours INTEGER,
    w_rain INTEGER, w_snow INTEGER, w_ts INTEGER, w_fzra INTEGER, w_fog INTEGER,
    w_precip_hours INTEGER,                      -- часов с осадками
    w_lowvis_hours INTEGER,                      -- часов с видимостью < 3 миль
    w_source        TEXT,                        -- metar (факт) / forecast (прогноз Open-Meteo)
    built_at        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS model_runs (          -- версии модели и их метрики
    model_version TEXT PRIMARY KEY,
    trained_at    TEXT NOT NULL,
    train_from    TEXT, train_to TEXT,
    metrics_json  TEXT,                          -- MAE/MAPE/покрытие модели и бейзлайна по целям
    importance_json TEXT                         -- важность признаков (permutation importance)
);

CREATE TABLE IF NOT EXISTS backtest (            -- прогноз vs факт на истории (rolling-origin)
    model_version TEXT NOT NULL,
    target        TEXT NOT NULL,
    date          TEXT NOT NULL,
    actual REAL, yhat REAL, yhat_lo REAL, yhat_hi REAL, baseline REAL,
    PRIMARY KEY (model_version, target, date)
);

CREATE TABLE IF NOT EXISTS predictions (
    target_date   TEXT NOT NULL,
    target        TEXT NOT NULL,                 -- dep_flown / dep_del15_share
    yhat REAL, yhat_lo REAL, yhat_hi REAL,
    baseline      REAL,                          -- норма (сезонный бейзлайн) для сравнения
    model_version TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    PRIMARY KEY (target_date, target, model_version)
);

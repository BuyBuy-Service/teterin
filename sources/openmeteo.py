"""S3. Прогноз погоды Open-Meteo (часть B, используется в прогнозе части C).

JSON с почасовым прогнозом на 7 дней -> сырой ответ в raw_forecast (дубль по sha256 не пишется)
-> таблица forecast_weather (по часу хранится последний прогноз).
Единицы приводим к METAR: ветер в узлах, видимость в милях.
"""
import hashlib
import json

import config
from db import connect
from pipeline import SourceError, http_get, job, now, set_watermark

SOURCE = "openmeteo"
HOURLY = ["temperature_2m", "precipitation", "snowfall", "wind_speed_10m", "wind_gusts_10m",
          "visibility", "cloud_cover", "weather_code"]
M_PER_MILE = 1609.344


@job("openmeteo", SOURCE)
def ingest(run):
    resp = http_get(config.OPENMETEO_URL, run, params={
        "latitude": config.AIRPORT_LAT, "longitude": config.AIRPORT_LON, "timezone": "UTC",
        "forecast_days": 7, "wind_speed_unit": "kn", "hourly": ",".join(HOURLY)})
    if resp.status_code != 200:
        raise SourceError(f"Open-Meteo: HTTP {resp.status_code}")
    payload = resp.text
    h = resp.json().get("hourly") or {}
    missing = [k for k in ["time", *HOURLY] if k not in h]
    if missing:
        raise SourceError(f"Open-Meteo: в ответе нет полей {missing}")

    fetched = now()
    rows = [(t + ":00Z", fetched, temp, pr, sn, w, g, None if v is None else v / M_PER_MILE, cc, wc)
            for t, temp, pr, sn, w, g, v, cc, wc in zip(h["time"], *(h[k] for k in HOURLY))]
    run.add(rows_fetched=len(rows))
    # хэш считаем только по данным: служебное поле generationtime_ms меняется в каждом ответе
    sha = hashlib.sha256(json.dumps(h, sort_keys=True).encode()).hexdigest()
    with connect() as con:
        before = con.total_changes
        con.execute("INSERT OR IGNORE INTO raw_forecast(fetched_at, sha256, payload_json) VALUES (?,?,?)",
                    (fetched, sha, payload))
        if con.total_changes == before:
            run.note("прогноз не изменился с прошлого запуска")
            run.add(rows_skipped=len(rows))
            return
        n_old = con.execute("SELECT count(*) FROM forecast_weather WHERE time_utc >= ?", (rows[0][0],)).fetchone()[0]
        con.executemany(
            """INSERT INTO forecast_weather VALUES (?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(time_utc) DO UPDATE SET fetched_at=excluded.fetched_at, temp_c=excluded.temp_c,
                 precip_mm=excluded.precip_mm, snow_cm=excluded.snow_cm, wind_kt=excluded.wind_kt,
                 gust_kt=excluded.gust_kt, vis_sm=excluded.vis_sm, cloud_cover=excluded.cloud_cover,
                 weather_code=excluded.weather_code""", rows)
        set_watermark(con, SOURCE, rows[0][0])  # начало последнего прогона прогноза
    run.add(rows_inserted=len(rows) - n_old, rows_updated=n_old)

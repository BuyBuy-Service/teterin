"""S3. Прогноз погоды Open-Meteo (часть B, используется в прогнозе части C).

JSON с почасовым прогнозом на 7 дней для аэропорта и аэропортов сети (одним запросом: Open-Meteo принимает
список координат) -> сырой ответ в raw_forecast (дубль по sha256 не пишется)
-> таблица forecast_weather (по станции и часу хранится последний прогноз).
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


def locations() -> dict[str, tuple[float, float]]:
    return {config.AIRPORT_IATA: (config.AIRPORT_LAT, config.AIRPORT_LON), **config.NETWORK}


@job("openmeteo", SOURCE)
def ingest(run):
    locs = locations()
    resp = http_get(config.OPENMETEO_URL, run, params={
        "latitude": ",".join(str(v[0]) for v in locs.values()),
        "longitude": ",".join(str(v[1]) for v in locs.values()), "timezone": "UTC",
        # 8 суток UTC: после перевода в местное время остаются 7 полных дней
        "forecast_days": 8, "wind_speed_unit": "kn", "hourly": ",".join(HOURLY)})
    if resp.status_code != 200:
        raise SourceError(f"Open-Meteo: HTTP {resp.status_code}")
    payload = resp.text
    data = resp.json()
    data = data if isinstance(data, list) else [data]  # для одной точки API отдаёт объект, для нескольких — список
    if len(data) != len(locs):
        raise SourceError(f"Open-Meteo: ожидали {len(locs)} точек, пришло {len(data)}")

    fetched = now()
    rows, hourly = [], {}
    for station, item in zip(locs, data):
        h = item.get("hourly") or {}
        missing = [k for k in ["time", *HOURLY] if k not in h]
        if missing:
            raise SourceError(f"Open-Meteo ({station}): в ответе нет полей {missing}")
        hourly[station] = h
        rows += [(station, t + ":00Z", fetched, temp, pr, sn, w, g, None if v is None else v / M_PER_MILE, cc, wc)
                 for t, temp, pr, sn, w, g, v, cc, wc in zip(h["time"], *(h[k] for k in HOURLY))]
    run.add(rows_fetched=len(rows))
    # хэш считаем только по данным: служебное поле generationtime_ms меняется в каждом ответе
    sha = hashlib.sha256(json.dumps(hourly, sort_keys=True).encode()).hexdigest()
    with connect() as con:
        before = con.total_changes
        con.execute("INSERT OR IGNORE INTO raw_forecast(fetched_at, sha256, payload_json) VALUES (?,?,?)",
                    (fetched, sha, payload))
        if con.total_changes == before:
            run.note("прогноз не изменился с прошлого запуска")
            run.add(rows_skipped=len(rows))
            return
        first = min(r[1] for r in rows)
        n_old = con.execute("SELECT count(*) FROM forecast_weather WHERE time_utc >= ?", (first,)).fetchone()[0]
        con.executemany(
            """INSERT INTO forecast_weather VALUES (?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(station, time_utc) DO UPDATE SET fetched_at=excluded.fetched_at, temp_c=excluded.temp_c,
                 precip_mm=excluded.precip_mm, snow_cm=excluded.snow_cm, wind_kt=excluded.wind_kt,
                 gust_kt=excluded.gust_kt, vis_sm=excluded.vis_sm, cloud_cover=excluded.cloud_cover,
                 weather_code=excluded.weather_code""", rows)
        set_watermark(con, SOURCE, first)  # начало последнего прогона прогноза
    run.add(rows_inserted=len(rows) - n_old, rows_updated=n_old)

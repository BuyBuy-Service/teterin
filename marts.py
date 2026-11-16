"""Витрина daily (часть C): одна строка = один день в аэропорту.

Факт по рейсам (BTS) + погода за день. Погода берётся:
  - для прошедших дней — из METAR (фактические наблюдения),
  - для сегодня и следующих дней — из прогноза Open-Meteo.
Признаки погоды выбраны так, чтобы считаться одинаково по обоим источникам (иначе модель обучится на
одном, а прогнозировать будет по другому): порывы, видимость, часы с осадками / плохой видимостью, флаги явлений.
Дни после последнего месяца BTS имеют пустой факт — для них модель строит прогноз.

Витрина пересобирается целиком (DELETE + INSERT в одной транзакции) — это ~800 строк, зато идемпотентно.
"""
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

import config
from db import connect
from pipeline import job, now

LOCAL = ZoneInfo(config.AIRPORT_TZ)

# коды погоды WMO в Open-Meteo
WMO_RAIN = set(range(51, 68)) | {80, 81, 82}
WMO_SNOW = set(range(71, 78)) | {85, 86}
WMO_FZRA = {56, 57, 66, 67}
WMO_TS = {95, 96, 99}
WMO_FOG = {45, 48}


def flights_daily(con) -> pd.DataFrame:
    dep = pd.read_sql("""
        SELECT flight_date AS date,
               count(*)                                   AS dep_scheduled,
               sum(cancelled = 0)                         AS dep_flown,
               sum(cancelled)                             AS dep_cancelled,
               avg(CASE WHEN cancelled = 0 THEN dep_del15 END) AS dep_del15_share,
               avg(CASE WHEN cancelled = 0 THEN dep_delay END) AS dep_delay_mean,
               sum(carrier_delay) AS min_carrier, sum(weather_delay) AS min_weather, sum(nas_delay) AS min_nas,
               sum(security_delay) AS min_security, sum(late_aircraft_delay) AS min_late_aircraft
        FROM flights WHERE is_deleted = 0 AND direction = 'departure' GROUP BY flight_date""", con)
    arr = pd.read_sql("""
        SELECT flight_date AS date, sum(cancelled = 0) AS arr_flown,
               avg(CASE WHEN cancelled = 0 THEN arr_del15 END) AS arr_del15_share
        FROM flights WHERE is_deleted = 0 AND direction = 'arrival' GROUP BY flight_date""", con)
    return dep.merge(arr, on="date", how="outer")


def to_local_date(ts_utc: pd.Series) -> pd.Series:
    return pd.to_datetime(ts_utc, utc=True).dt.tz_convert(config.AIRPORT_TZ).dt.strftime("%Y-%m-%d")


def metar_daily(con) -> pd.DataFrame:
    w = pd.read_sql("SELECT * FROM weather_obs WHERE parse_ok = 1", con)
    if w.empty:
        return pd.DataFrame(columns=["date"])
    t = pd.to_datetime(w["observed_at_utc"], utc=True)
    w["date"] = to_local_date(w["observed_at_utc"])
    w["hour"] = t.dt.floor("h")
    w["gust"] = w["gust_kt"].fillna(w["wind_kt"])
    w["ifr"] = w["flight_cat"].isin(["IFR", "LIFR"])
    w["lowvis"] = w["vis_sm"] < 3
    g = w.groupby("date")
    hours = lambda col: w[w[col].astype(bool)].groupby("date")["hour"].nunique()  # noqa: E731
    return pd.DataFrame({
        "w_min_vis": g["vis_sm"].min(), "w_max_gust": g["gust"].max(),
        "w_ifr_hours": hours("ifr"), "w_precip_hours": hours("precip"), "w_lowvis_hours": hours("lowvis"),
        "w_rain": g["rain"].max(), "w_snow": g["snow"].max(), "w_ts": g["ts"].max(),
        "w_fzra": g["fzra"].max(), "w_fog": g["fog"].max(),
    }).fillna({"w_ifr_hours": 0, "w_precip_hours": 0, "w_lowvis_hours": 0}).reset_index().assign(w_source="metar")


def forecast_daily(con) -> pd.DataFrame:
    f = pd.read_sql("SELECT * FROM forecast_weather", con)
    if f.empty:
        return pd.DataFrame(columns=["date"])
    f["date"] = to_local_date(f["time_utc"])
    code = f["weather_code"].fillna(0).astype(int)
    f["rain"], f["snow"] = code.isin(WMO_RAIN), code.isin(WMO_SNOW) | (f["snow_cm"] > 0)
    f["fzra"], f["ts"], f["fog"] = code.isin(WMO_FZRA), code.isin(WMO_TS), code.isin(WMO_FOG)
    f["precip"] = f["precip_mm"] >= 0.1
    f["lowvis"] = f["vis_sm"] < 3
    g = f.groupby("date")
    d = pd.DataFrame({
        "w_min_vis": g["vis_sm"].min(), "w_max_gust": g["gust_kt"].max(),
        "w_ifr_hours": g["lowvis"].sum(),  # потолка в прогнозе нет -> IFR оцениваем по видимости
        "w_precip_hours": g["precip"].sum(), "w_lowvis_hours": g["lowvis"].sum(),
        "w_rain": g["rain"].max(), "w_snow": g["snow"].max(), "w_ts": g["ts"].max(),
        "w_fzra": g["fzra"].max(), "w_fog": g["fog"].max(), "n_hours": g.size(),
    })
    d = d[d["n_hours"] >= 20].drop(columns="n_hours")  # неполные сутки на краях прогноза отбрасываем
    return d.astype(float).reset_index().assign(w_source="forecast")


@job("marts")
def build(run):
    with connect() as con:
        fl = flights_daily(con)
        today = datetime.now(LOCAL).strftime("%Y-%m-%d")
        wm = metar_daily(con)
        wm = wm[wm["date"] < today]            # прошедшие дни — по факту
        wf = forecast_daily(con)
        wf = wf[wf["date"] >= today]           # сегодня и дальше — по прогнозу
        weather = pd.concat([wm, wf], ignore_index=True)
        df = fl.merge(weather, on="date", how="outer").sort_values("date")
        df = df[df["date"] >= config.HISTORY_START.isoformat()]
        df["built_at"] = now()
        cols = [r[1] for r in con.execute("PRAGMA table_info(daily)")]
        df = df.reindex(columns=cols)
        df = df.astype(object).where(df.notna(), None)
        con.execute("DELETE FROM daily")
        con.executemany(f"INSERT INTO daily VALUES ({', '.join('?' * len(cols))})", df.itertuples(index=False))
    run.add(rows_fetched=len(df), rows_inserted=len(df))

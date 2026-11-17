"""Витрина daily (часть C): одна строка = один день в аэропорту.

Факт по рейсам (BTS) + погода за день. Погода берётся:
  - для прошедших дней — из METAR (фактические наблюдения),
  - для сегодня и следующих дней — из прогноза Open-Meteo.
Признаки погоды выбраны так, чтобы считаться одинаково по обоим источникам (иначе модель обучится на
одном, а прогнозировать будет по другому): порывы, видимость, часы с осадками / плохой видимостью, флаги явлений.
Дни после последнего месяца BTS имеют пустой факт — для них модель строит прогноз.
Плюс погода в 10 аэропортах, куда летит больше всего рейсов (config.NETWORK), — признаки n_*.

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


def _in(stations) -> str:
    return ",".join(f"'{x}'" for x in stations)  # коды станций — из нашего конфига, не от пользователя


def metar_daily(con, stations) -> pd.DataFrame:
    """Погодные признаки по станции и дню (по местной дате ORD) из фактических METAR."""
    w = pd.read_sql(f"SELECT * FROM weather_obs WHERE parse_ok = 1 AND station IN ({_in(stations)})", con)
    if w.empty:
        return pd.DataFrame(columns=["station", "date"])
    t = pd.to_datetime(w["observed_at_utc"], utc=True)
    w["date"] = to_local_date(w["observed_at_utc"])
    w["hour"] = t.dt.floor("h")
    w["gust"] = w["gust_kt"].fillna(w["wind_kt"])
    w["ifr"] = w["flight_cat"].isin(["IFR", "LIFR"])
    w["lowvis"] = w["vis_sm"] < 3
    keys = ["station", "date"]
    g = w.groupby(keys)
    hours = lambda col: w[w[col].astype(bool)].groupby(keys)["hour"].nunique()  # noqa: E731
    return pd.DataFrame({
        "w_min_vis": g["vis_sm"].min(), "w_max_gust": g["gust"].max(),
        "w_ifr_hours": hours("ifr"), "w_precip_hours": hours("precip"), "w_lowvis_hours": hours("lowvis"),
        "w_rain": g["rain"].max(), "w_snow": g["snow"].max(), "w_ts": g["ts"].max(),
        "w_fzra": g["fzra"].max(), "w_fog": g["fog"].max(),
    }).fillna({"w_ifr_hours": 0, "w_precip_hours": 0, "w_lowvis_hours": 0}).reset_index().assign(w_source="metar")


def forecast_daily(con, stations) -> pd.DataFrame:
    """Те же признаки из почасового прогноза Open-Meteo."""
    f = pd.read_sql(f"SELECT * FROM forecast_weather WHERE station IN ({_in(stations)})", con)
    if f.empty:
        return pd.DataFrame(columns=["station", "date"])
    f["date"] = to_local_date(f["time_utc"])
    code = f["weather_code"].fillna(0).astype(int)
    f["rain"], f["snow"] = code.isin(WMO_RAIN), code.isin(WMO_SNOW) | (f["snow_cm"] > 0)
    f["fzra"], f["ts"], f["fog"] = code.isin(WMO_FZRA), code.isin(WMO_TS), code.isin(WMO_FOG)
    f["precip"] = f["precip_mm"] >= 0.1
    f["lowvis"] = f["vis_sm"] < 3
    g = f.groupby(["station", "date"])
    d = pd.DataFrame({
        "w_min_vis": g["vis_sm"].min(), "w_max_gust": g["gust_kt"].max(),
        "w_ifr_hours": g["lowvis"].sum(),  # потолка в прогнозе нет -> IFR оцениваем по видимости
        "w_precip_hours": g["precip"].sum(), "w_lowvis_hours": g["lowvis"].sum(),
        "w_rain": g["rain"].max(), "w_snow": g["snow"].max(), "w_ts": g["ts"].max(),
        "w_fzra": g["fzra"].max(), "w_fog": g["fog"].max(), "n_hours": g.size(),
    })
    d = d[d["n_hours"] >= 20].drop(columns="n_hours")  # неполные сутки на краях прогноза отбрасываем
    return d.astype(float).reset_index().assign(w_source="forecast")


def weather_daily(con, stations, today: str) -> pd.DataFrame:
    """Прошедшие дни — по факту (METAR), сегодня и дальше — по прогнозу."""
    wm = metar_daily(con, stations)
    wf = forecast_daily(con, stations)
    return pd.concat([wm[wm["date"] < today], wf[wf["date"] >= today]], ignore_index=True)


def network_daily(con, today: str) -> pd.DataFrame:
    """Погода в аэропортах сети, взвешенная по доле рейсов из ORD в каждый из них.
    n_severe — доля рейсов, которые летят туда, где в этот день опасная погода
    (гроза, ледяной дождь, снег, ≥ 3 ч плохой видимости или порывы ≥ 35 узлов)."""
    st = sorted(config.NETWORK)
    if not st:
        return pd.DataFrame(columns=["date"])
    d = weather_daily(con, st, today)
    if d.empty:
        return pd.DataFrame(columns=["date"])
    share = pd.read_sql(f"""SELECT dest AS station, count(*) AS n FROM flights
                            WHERE direction = 'departure' AND is_deleted = 0 AND dest IN ({_in(st)})
                            GROUP BY dest""", con).set_index("station")["n"]
    d["w"] = d["station"].map(share).fillna(share.mean() if len(share) else 1.0)
    d["severe"] = ((d["w_ts"] > 0) | (d["w_fzra"] > 0) | (d["w_snow"] > 0) | (d["w_lowvis_hours"] >= 3)
                   | (d["w_max_gust"] >= 35)).astype(float)
    wavg = lambda g, col: (g[col].astype(float) * g["w"]).sum() / g["w"].sum()  # noqa: E731
    out = d.groupby("date").apply(lambda g: pd.Series({
        "n_severe": wavg(g, "severe"), "n_ts": wavg(g, "w_ts"), "n_snow": wavg(g, "w_snow"),
        "n_lowvis": wavg(g, "w_lowvis_hours")}), include_groups=False)
    return out.reset_index()


def flights_with_weather(con, d0: str, d1: str) -> pd.DataFrame:
    """Каждому выполненному вылету — последняя METAR-сводка ORD не старше 90 минут до планового вылета.
    Плановое время в BTS — местное (hhmm), сводки — в UTC: переводим вылет в UTC с учётом перехода на летнее время."""
    f = pd.read_sql("""SELECT flight_date, crs_dep_time, dep_del15 FROM flights
                       WHERE direction = 'departure' AND is_deleted = 0 AND cancelled = 0
                         AND dep_del15 IS NOT NULL AND flight_date BETWEEN ? AND ?""", con, params=(d0, d1))
    w = pd.read_sql("""SELECT observed_at_utc, flight_cat, gust_kt, wind_kt, vis_sm, rain, snow, fzra, ts, fog, precip
                       FROM weather_obs WHERE parse_ok = 1 AND station = ?""", con, params=(config.AIRPORT_IATA,))
    hhmm = f["crs_dep_time"].clip(upper=2359)  # в BTS встречается 2400
    local = pd.to_datetime(f["flight_date"]) + pd.to_timedelta(hhmm // 100, "h") + pd.to_timedelta(hhmm % 100, "m")
    f["t"] = local.dt.tz_localize(config.AIRPORT_TZ, ambiguous="NaT", nonexistent="shift_forward").dt.tz_convert("UTC")
    f["hour"], f["dow"] = local.dt.hour, local.dt.day_of_week
    f = f.dropna(subset=["t"]).sort_values("t")
    w["t"] = pd.to_datetime(w["observed_at_utc"], utc=True)
    w = w.sort_values("t")
    return pd.merge_asof(f, w, on="t", direction="backward", tolerance=pd.Timedelta(minutes=90))


def weather_groups(fw: pd.DataFrame) -> dict:
    """Группы вылетов по погоде в момент вылета (для дашборда и отчёта)."""
    gust = fw["gust_kt"].fillna(fw["wind_kt"])
    calm = (fw["precip"] == 0) & (fw["fog"] == 0) & (fw["ts"] == 0) & (gust < 30)
    return {
        "categories": {"VFR — хорошие": fw["flight_cat"] == "VFR", "MVFR — сложные": fw["flight_cat"] == "MVFR",
                       "IFR — по приборам": fw["flight_cat"] == "IFR", "LIFR — очень плохие": fw["flight_cat"] == "LIFR"},
        "phenomena": {"Без явлений": calm, "Дождь": (fw["rain"] == 1) & (fw["snow"] == 0), "Снег": fw["snow"] == 1,
                      "Ледяной дождь": fw["fzra"] == 1, "Гроза": fw["ts"] == 1, "Туман": fw["fog"] == 1,
                      "Порывы ≥ 30 уз": gust >= 30},
    }


@job("marts")
def build(run):
    with connect() as con:
        fl = flights_daily(con)
        today = datetime.now(LOCAL).strftime("%Y-%m-%d")
        weather = weather_daily(con, [config.AIRPORT_IATA], today).drop(columns="station")
        net = network_daily(con, today)
        df = fl.merge(weather, on="date", how="outer").merge(net, on="date", how="left").sort_values("date")
        df = df[df["date"] >= config.HISTORY_START.isoformat()]
        df["built_at"] = now()
        cols = [r[1] for r in con.execute("PRAGMA table_info(daily)")]
        df = df.reindex(columns=cols)
        df = df.astype(object).where(df.notna(), None)
        con.execute("DELETE FROM daily")
        con.executemany(f"INSERT INTO daily VALUES ({', '.join('?' * len(cols))})", df.itertuples(index=False))
    run.add(rows_fetched=len(df), rows_inserted=len(df))

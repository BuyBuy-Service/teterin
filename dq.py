"""Контроль качества данных (часть A).

Каждое правило считает: сколько записей проверено, сколько не прошло, примеры ключей.
Результаты пишутся в dq_log и показываются на странице «Журнал и качество».
severity: error — данные явно некорректны; warning — подозрительно, но возможно.
"""
import json
from datetime import datetime, timezone

import pandas as pd

from db import connect
from pipeline import job, now

ACTIVE = "is_deleted = 0"

# SQL-правила: (код, severity, описание, FROM/WHERE проверяемого множества, условие ошибки, ключ для примеров)
SQL_RULES = [
    ("flights_dep_delay_missing", "error", "Нет задержки у выполненного вылета",
     f"flights WHERE {ACTIVE} AND direction = 'departure' AND cancelled = 0 AND diverted = 0",
     "dep_delay IS NULL", "flight_date || ' ' || carrier || flight_number"),
    ("flights_delay_range", "error", "Задержка вне диапазона −60…2000 мин",
     f"flights WHERE {ACTIVE} AND dep_delay IS NOT NULL",
     "dep_delay < -60 OR dep_delay > 2000", "flight_date || ' ' || carrier || flight_number"),
    ("flights_del15_consistent", "error", "Флаг DepDel15 не согласован с минутами задержки",
     f"flights WHERE {ACTIVE} AND dep_delay IS NOT NULL",
     "dep_del15 IS NOT (dep_delay >= 15)", "flight_date || ' ' || carrier || flight_number"),
    ("flights_cancelled_no_dep", "warning", "Отменённый рейс имеет фактическое время вылета",
     f"flights WHERE {ACTIVE} AND cancelled = 1",
     "dep_time IS NOT NULL", "flight_date || ' ' || carrier || flight_number"),
    ("flights_cause_sum", "warning", "Сумма минут по причинам ≠ задержке прибытия (при задержке ≥15)",
     f"flights WHERE {ACTIVE} AND arr_delay >= 15",
     "abs(coalesce(carrier_delay,0) + coalesce(weather_delay,0) + coalesce(nas_delay,0)"
     " + coalesce(security_delay,0) + coalesce(late_aircraft_delay,0) - arr_delay) > 1",
     "flight_date || ' ' || carrier || flight_number"),
    ("weather_ranges", "error", "Погода вне физических диапазонов (t −50…50 °C, ветер <150 уз, видимость ≥0)",
     "weather_obs WHERE parse_ok = 1",
     "temp_c NOT BETWEEN -50 AND 50 OR wind_kt >= 150 OR gust_kt >= 150 OR vis_sm < 0", "observed_at_utc"),
    ("weather_parse_failed", "warning", "METAR не удалось разобрать",
     "weather_obs", "parse_ok = 0", "raw_text"),
    ("forecast_ranges", "error", "Прогноз погоды вне диапазонов",
     "forecast_weather", "temp_c NOT BETWEEN -50 AND 50 OR gust_kt >= 150 OR precip_mm < 0", "time_utc"),
]

# свежесть: источник -> (допустимый возраст, единица)
FRESHNESS = {"bts": (24 * 35, "ч"), "metar": (3, "ч"), "openmeteo": (12, "ч")}


@job("dq")
def run(run):
    results = []
    with connect() as con:
        for code, sev, _desc, scope, bad, key in SQL_RULES:
            checked = con.execute(f"SELECT count(*) FROM {scope}").fetchone()[0]
            failed = con.execute(f"SELECT count(*) FROM {scope} AND ({bad})" if " WHERE " in scope
                                 else f"SELECT count(*) FROM {scope} WHERE {bad}").fetchone()[0]
            sample = []
            if failed:
                where = f"{scope} AND ({bad})" if " WHERE " in scope else f"{scope} WHERE {bad}"
                sample = [r[0] for r in con.execute(f"SELECT {key} FROM {where} LIMIT 5")]
            results.append((code, sev, checked, failed, sample))
        results.append(daily_volume(con))
        results.append(metar_gaps(con))
        results += freshness(con)

        ts = now()
        con.executemany(
            "INSERT INTO dq_log(run_id, rule, severity, checked, failed, sample, checked_at) VALUES (?,?,?,?,?,?,?)",
            [(run.id, c, s, ch, f, json.dumps(smp, ensure_ascii=False), ts) for c, s, ch, f, smp in results])
    run.add(rows_fetched=sum(r[2] for r in results))
    bad = [f"{c}: {f}" for c, s, ch, f, _ in results if f and s == "error"]
    if bad:
        run.note("ошибки качества — " + ", ".join(bad))


def daily_volume(con):
    """Число вылетов за день вне ±3σ от скользящей 28-дневной нормы (по тому же дню недели не дробим — грубо, но наглядно)."""
    df = pd.read_sql(
        f"SELECT flight_date d, count(*) n FROM flights WHERE {ACTIVE} AND direction = 'departure' GROUP BY 1 ORDER BY 1",
        con)
    if len(df) < 30:
        return ("flights_daily_volume", "warning", len(df), 0, [])
    roll = df["n"].rolling(28, min_periods=14)
    mean, std = roll.mean().shift(1), roll.std().shift(1)
    out = df[(df["n"] - mean).abs() > 3 * std]
    return ("flights_daily_volume", "warning", len(df), len(out),
            [f"{r.d}: {r.n}" for r in out.head(5).itertuples()])


def metar_gaps(con):
    """Дыры в METAR больше 2 часов (сводки должны идти ежечасно)."""
    t = pd.to_datetime(pd.read_sql("SELECT DISTINCT observed_at_utc t FROM raw_metar ORDER BY 1", con)["t"])
    gaps = t.diff() > pd.Timedelta(hours=2)
    return ("metar_gaps_2h", "warning", len(t), int(gaps.sum()),
            [f"{a} → {b}" for a, b in zip(t.shift(1)[gaps].astype(str).head(5), t[gaps].astype(str).head(5))])


def freshness(con):
    out = []
    # момент последнего успешного запуска каждой джобы загрузки
    marks = dict(con.execute(
        "SELECT job, max(finished_at) FROM load_log WHERE status = 'success' GROUP BY job").fetchall())
    t_now = datetime.now(timezone.utc)
    # BTS: важна не дата запуска, а последний опубликованный месяц
    wm = con.execute("SELECT value FROM watermarks WHERE source = 'bts'").fetchone()
    if wm:
        lag = (t_now.year * 12 + t_now.month) - (int(wm[0][:4]) * 12 + int(wm[0][5:]))
        out.append(("freshness_bts_period", "warning", 1, int(lag > 4),
                    [f"последний месяц BTS {wm[0]}, отставание {lag} мес. (норма для BTS — 2–3)"]))
    for src, (limit_h, unit) in FRESHNESS.items():
        if src not in marks:
            out.append((f"freshness_{src}", "warning", 1, 1, ["источник ни разу не загружался"]))
            continue
        age_h = (t_now - datetime.fromisoformat(marks[src].replace("Z", "+00:00"))).total_seconds() / 3600
        out.append((f"freshness_{src}", "warning", 1, int(age_h > limit_h),
                    [f"последнее обновление {age_h:.1f} ч назад, порог {limit_h} {unit}"]))
    return out


RULE_DESCRIPTIONS = {c: d for c, _s, d, *_ in SQL_RULES} | {
    "flights_daily_volume": "Число вылетов за день вне ±3σ от 28-дневной нормы",
    "metar_gaps_2h": "Перерывы в METAR-сводках больше 2 часов",
    "freshness_bts": "Давно не запускалась загрузка BTS (>35 дней)",
    "freshness_bts_period": "Последний месяц BTS отстаёт больше чем на 4 месяца",
    "freshness_metar": "METAR не обновлялся больше 3 ч", "freshness_openmeteo": "Прогноз погоды не обновлялся больше 12 ч",
}

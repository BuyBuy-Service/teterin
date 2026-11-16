"""Прогнозная модель (часть C).

Цели (дневной уровень, вылеты из аэропорта):
  dep_del15_share — доля вылетов с задержкой ≥ 15 мин;
  dep_flown       — число выполненных (не отменённых) вылетов.

Бейзлайн («норма»): см. norm() — среднее по дню недели и месяцу (задержки) или тот же день год назад (рейсы).
Модель: HistGradientBoosting (loss = абсолютная ошибка, т.е. прогноз медианы) на календаре + погоде дня.
Интервал 10–90%: прогноз + квантили ошибок модели на backtest (факт должен попадать в него ~80% дней).
Квантильные бустинги пробовали — на ~700 днях они переобучаются, покрытие было 30–55% вместо 80%.

Утечки будущего нет: признаки — только календарь, погода этого дня (факт METAR в истории, прогноз Open-Meteo
для будущего) и значение цели год назад (364 дня — больше любого горизонта прогноза).

Оценка: rolling-origin backtest — для каждого из последних 6 месяцев учимся только на данных до него
и прогнозируем его. Метрики: MAE, MAPE, покрытие интервала; сравнение с бейзлайном.
Ограничение: в backtest погода фактическая, т.е. «идеальный прогноз погоды» — реальная точность чуть хуже.
"""
import json

import holidays
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.inspection import permutation_importance

from db import connect
from pipeline import job, now

TARGETS = {
    "dep_del15_share": "Доля вылетов с задержкой ≥ 15 мин",
    "dep_flown": "Число выполненных вылетов",
}
WEATHER = ["w_min_vis", "w_max_gust", "w_precip_hours", "w_lowvis_hours",
           "w_rain", "w_snow", "w_ts", "w_fzra", "w_fog"]
CALENDAR = ["dow", "month", "doy_sin", "doy_cos", "holiday_dist"]
BACKTEST_MONTHS = 6
HGB = dict(max_iter=300, learning_rate=0.05, max_leaf_nodes=15, min_samples_leaf=20, random_state=42)


def load() -> pd.DataFrame:
    with connect() as con:
        df = pd.read_sql("SELECT * FROM daily ORDER BY date", con)
    df["date"] = pd.to_datetime(df["date"])
    return df


def add_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    d = df["date"]
    df["dow"], df["month"] = d.dt.day_of_week, d.dt.month
    doy = d.dt.day_of_year
    df["doy_sin"], df["doy_cos"] = np.sin(2 * np.pi * doy / 365.25), np.cos(2 * np.pi * doy / 365.25)
    hol = pd.to_datetime(list(holidays.US(years=range(d.dt.year.min() - 1, d.dt.year.max() + 2)).keys()))
    # расстояние до ближайшего праздника в днях, не больше 7 (перед праздниками пассажиропоток другой)
    df["holiday_dist"] = [min(7, int(np.abs((hol - x).days).min())) for x in d]
    df["w_min_vis"] = df["w_min_vis"].clip(upper=10)  # METAR пишет «10SM» как максимум, прогноз — до 15+
    by_date = df.set_index("date")
    for t in TARGETS:  # значение цели ровно 52 недели назад (тот же день недели)
        df[f"{t}_ly"] = by_date[t].reindex(d - pd.Timedelta(days=364)).to_numpy()
    return df


def features(target: str) -> list[str]:
    return CALENDAR + WEATHER + ([f"{target}_ly"] if target == "dep_flown" else [])


def norm(train: pd.DataFrame, rows: pd.DataFrame, target: str) -> np.ndarray:
    """Бейзлайн («норма»).
    Доля задержек: среднее по (день недели, месяц) в обучающих данных, если нет — по дню недели.
    Число рейсов: тот же день недели год назад (364 дня) — число вылетов ORD за год выросло на 17%,
    и среднее по годам занижало бы норму. Если года назад данных нет — среднее по (день недели, месяц)."""
    by_dm = train.groupby(["dow", "month"])[target].mean()
    by_d = train.groupby("dow")[target].mean()
    keys = list(zip(rows["dow"], rows["month"]))
    avg = np.array([by_dm.get(k, by_d.get(k[0], np.nan)) for k in keys])
    if target == "dep_flown":
        return np.where(rows[f"{target}_ly"].notna(), rows[f"{target}_ly"], avg)
    return avg


def fit(train: pd.DataFrame, target: str) -> HistGradientBoostingRegressor:
    return HistGradientBoostingRegressor(loss="absolute_error", **HGB).fit(train[features(target)], train[target])


def interval(residuals) -> tuple[float, float]:
    """Интервал 10–90% по ошибкам прогноза на отложенных данных (эмпирический / конформный подход)."""
    lo, hi = np.quantile(np.asarray(residuals, float), [0.1, 0.9])
    return min(lo, 0.0), max(hi, 0.0)


def predict(model, rows: pd.DataFrame, target: str, offsets=(0.0, 0.0)) -> pd.DataFrame:
    mid = model.predict(rows[features(target)])
    lo, hi = mid + offsets[0], mid + offsets[1]
    if target == "dep_del15_share":
        mid, lo, hi = (np.clip(a, 0, 1) for a in (mid, lo, hi))
    return pd.DataFrame({"yhat": mid, "yhat_lo": lo, "yhat_hi": hi}, index=rows.index)


def metrics(actual, pred, lo=None, hi=None) -> dict:
    a, p = np.asarray(actual, float), np.asarray(pred, float)
    m = {"mae": float(np.mean(np.abs(a - p))),
         "mape": float(np.mean(np.abs(a - p) / np.where(a == 0, np.nan, np.abs(a))) * 100)}
    if lo is not None:
        m["coverage"] = float(np.mean((a >= lo) & (a <= hi)) * 100)
    return m


def backtest(df: pd.DataFrame, target: str):
    """Rolling-origin: каждый из последних месяцев прогнозируем моделью, обученной только на данных до него.
    Интервал для месяца строим по ошибкам на ОСТАЛЬНЫХ месяцах — чтобы покрытие было честным."""
    hist = df[df[target].notna() & df["w_source"].notna()]
    months = hist["date"].dt.to_period("M").unique()[-BACKTEST_MONTHS:]
    parts, last = [], None
    for m in months:
        train, test = hist[hist["date"] < m.to_timestamp()], hist[hist["date"].dt.to_period("M") == m]
        if len(train) < 180 or test.empty:
            continue
        mdl = fit(train, target)
        p = predict(mdl, test, target)
        p["actual"], p["baseline"], p["date"], p["fold"] = test[target], norm(train, test, target), test["date"], str(m)
        parts.append(p)
        last = (mdl, test)
    bt = pd.concat(parts)
    resid = bt["actual"] - bt["yhat"]
    for f in bt["fold"].unique():
        lo, hi = interval(resid[bt["fold"] != f])
        k = bt["fold"] == f
        bt.loc[k, "yhat_lo"], bt.loc[k, "yhat_hi"] = bt.loc[k, "yhat"] + lo, bt.loc[k, "yhat"] + hi
    if target == "dep_del15_share":
        bt[["yhat_lo", "yhat_hi"]] = bt[["yhat_lo", "yhat_hi"]].clip(0, 1)
    return bt, last, interval(resid)


def importance(mdl, test: pd.DataFrame, target: str) -> dict:
    r = permutation_importance(mdl, test[features(target)], test[target],
                               scoring="neg_mean_absolute_error", n_repeats=10, random_state=42)
    return dict(sorted(zip(features(target), map(float, r.importances_mean)), key=lambda kv: -kv[1]))


@job("model")
def train_and_predict(run):
    df = add_features(load())
    version = "hgb-" + now()
    metrics_all, imp_all, bt_rows, pred_rows = {}, {}, [], []
    for target in TARGETS:
        bt, (last_model, last_test), offsets = backtest(df, target)
        metrics_all[target] = {
            "model": metrics(bt["actual"], bt["yhat"], bt["yhat_lo"], bt["yhat_hi"]),
            "baseline": metrics(bt["actual"], bt["baseline"]),
            "n_days": len(bt), "from": bt["date"].min().strftime("%Y-%m-%d"), "to": bt["date"].max().strftime("%Y-%m-%d"),
        }
        imp_all[target] = importance(last_model, last_test, target)
        bt_rows += [(version, target, r.date.strftime("%Y-%m-%d"), r.actual, r.yhat, r.yhat_lo, r.yhat_hi, r.baseline)
                    for r in bt.itertuples()]

        # финальная модель на всей истории -> прогноз на дни без факта, где известна погода
        hist = df[df[target].notna() & df["w_source"].notna()]
        future = df[(df["date"] > hist["date"].max()) & df["w_source"].notna()]
        p = predict(fit(hist, target), future, target, offsets)
        p["baseline"] = norm(hist, future, target)
        pred_rows += [(d.strftime("%Y-%m-%d"), target, r.yhat, r.yhat_lo, r.yhat_hi, r.baseline, version, now())
                      for d, r in zip(future["date"], p.itertuples())]
        mm, mb = metrics_all[target]["model"], metrics_all[target]["baseline"]
        print(f"  {target}: MAE модели {mm['mae']:.4g} vs бейзлайн {mb['mae']:.4g}, "
              f"покрытие {mm['coverage']:.0f}%, прогноз на {len(future)} дн.")
        train_range = (hist["date"].min().strftime("%Y-%m-%d"), hist["date"].max().strftime("%Y-%m-%d"))

    with connect() as con:
        con.execute("INSERT INTO model_runs VALUES (?,?,?,?,?,?)",
                    (version, now(), *train_range, json.dumps(metrics_all), json.dumps(imp_all)))
        con.executemany("INSERT INTO backtest VALUES (?,?,?,?,?,?,?,?)", bt_rows)
        con.executemany("INSERT INTO predictions VALUES (?,?,?,?,?,?,?,?)", pred_rows)
    run.add(rows_fetched=len(df), rows_inserted=len(pred_rows))

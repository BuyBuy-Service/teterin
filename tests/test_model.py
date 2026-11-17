"""Часть C: признаки модели не заглядывают в будущее; бейзлайн и метрики считаются как задумано."""
import numpy as np
import pandas as pd

import model


def synthetic(days=800, seed=0):
    rng = np.random.default_rng(seed)
    d = pd.date_range("2024-09-01", periods=days, freq="D")
    snow = rng.random(days) < 0.1
    df = pd.DataFrame({
        "date": d, "w_source": "metar",
        "w_min_vis": np.where(snow, 1.0, 10.0), "w_max_gust": rng.uniform(5, 40, days),
        "w_precip_hours": snow * 8, "w_lowvis_hours": snow * 6,
        "w_rain": 0, "w_snow": snow.astype(int), "w_ts": 0, "w_fzra": 0, "w_fog": 0,
        "n_severe": rng.random(days), "n_ts": 0.0, "n_snow": 0.0, "n_lowvis": 0.0,
    })
    df["dep_del15_share"] = 0.15 + 0.2 * snow + rng.normal(0, 0.03, days)
    df["dep_flown"] = 1000 + 50 * (d.day_of_week < 5) - 150 * snow + rng.normal(0, 20, days)
    return df


def test_no_future_leak_in_features():
    df = model.add_features(synthetic())
    for t in model.TARGETS:
        assert t not in model.features(t)
        # единственный признак из прошлых значений цели — ровно 364 дня назад
        lagged = [f for f in model.features(t) if f.endswith("_ly")]
        assert all(f == f"{t}_ly" for f in lagged)
    i = 400
    assert df.loc[i, "dep_flown_ly"] == df.loc[i - 364, "dep_flown"]
    assert np.isnan(df.loc[10, "dep_flown_ly"])  # года назад данных нет -> пусто, а не «подсмотренное»


def test_changing_future_does_not_change_past_prediction():
    df = model.add_features(synthetic())
    train, test = df.iloc[:600], df.iloc[600:610]
    p1 = model.predict(model.fit(train, "dep_del15_share"), test, "dep_del15_share")
    df2 = synthetic()
    df2.loc[650:, "dep_del15_share"] = 0.99  # «испортили» будущее
    df2 = model.add_features(df2)
    p2 = model.predict(model.fit(df2.iloc[:600], "dep_del15_share"), df2.iloc[600:610], "dep_del15_share")
    assert np.allclose(p1["yhat"], p2["yhat"])


def test_model_beats_baseline_on_weather_driven_data():
    bt, _, _ = model.backtest(model.add_features(synthetic()), "dep_del15_share")
    m, b = model.metrics(bt["actual"], bt["yhat"]), model.metrics(bt["actual"], bt["baseline"])
    assert m["mae"] < b["mae"]
    assert ((bt["yhat_lo"] <= bt["yhat"]) & (bt["yhat"] <= bt["yhat_hi"])).all()

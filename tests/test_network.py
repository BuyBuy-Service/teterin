"""Погода в аэропортах сети: признаки взвешиваются по доле рейсов; загрузка BTS дозаполняет дыры в истории."""
from datetime import date

import pytest

import config
import marts
from db import connect
from sources import bts


@pytest.fixture
def network(monkeypatch):
    monkeypatch.setattr(config, "NETWORK", {"LGA": (40.7, -73.8), "LAX": (33.9, -118.4)})


def add_flights(con, dest, n):
    con.executemany(
        "INSERT INTO flights(flight_date, carrier, flight_number, origin, dest, crs_dep_time, direction, cancelled, "
        "diverted, updated_at) VALUES ('2026-01-05', 'UA', ?, 'ORD', ?, 700, 'departure', 0, 0, 'x')",
        [(i + (0 if dest == "LGA" else 1000), dest) for i in range(n)])


def add_obs(con, station, raw_flags):
    """Одна сводка в 18:51 UTC 05.01 (12:51 по Чикаго), флаги явлений — словарь."""
    f = dict(temp_c=0, wind_kt=10, gust_kt=None, vis_sm=10, ceiling_ft=None, precip=0, rain=0, snow=0, fzra=0,
             ts=0, fog=0, mist=0, flight_cat="VFR", parse_ok=1) | raw_flags
    con.execute(f"INSERT INTO weather_obs VALUES (?, '2026-01-05 18:51', 'txt', {', '.join('?' * len(f))})",
                (station, *f.values()))


def test_network_weighted_by_flight_share(network):
    with connect() as con:
        add_flights(con, "LGA", 3)   # 3 рейса в Нью-Йорк
        add_flights(con, "LAX", 1)   # 1 рейс в Лос-Анджелес
        add_obs(con, "LGA", {"ts": 1, "precip": 1, "rain": 1})  # гроза в Нью-Йорке
        add_obs(con, "LAX", {})                                 # в Лос-Анджелесе спокойно
        net = marts.network_daily(con, today="2026-02-01").set_index("date")
    row = net.loc["2026-01-05"]
    assert row["n_severe"] == pytest.approx(0.75)   # 3 из 4 рейсов летят в грозу
    assert row["n_ts"] == pytest.approx(0.75)
    assert row["n_snow"] == pytest.approx(0.0)


def test_network_uses_forecast_for_future_days(network):
    with connect() as con:
        add_flights(con, "LGA", 1)
        add_obs(con, "LGA", {"snow": 1, "precip": 1})  # факт до «сегодня» учитывается
        net = marts.network_daily(con, today="2026-01-05")  # 05.01 — уже «сегодня»: факт не берём, прогноза нет
    assert net.empty or "2026-01-05" not in set(net["date"])


def test_bts_fills_gaps_in_history(tmp_path, monkeypatch):
    """История удлинилась: загрузка запрашивает и месяцы до отметки загрузки, которых нет в raw_files."""
    monkeypatch.setattr(config, "HISTORY_START", date(2026, 1, 1))
    requested = []

    def fake_download(run, period):
        requested.append(period)
        return None  # «не опубликован»: нам важно только, какие месяцы запрошены

    monkeypatch.setattr(bts, "download", fake_download)
    with connect() as con:
        for p in ("2026-02", "2026-03"):
            con.execute("INSERT INTO raw_files(source, period, sha256, path, loaded_at) VALUES ('bts', ?, ?, 'x', 'x')",
                        (p, p))
        con.execute("INSERT INTO watermarks VALUES ('bts', '2026-03', 'x')")
    r = bts.ingest()
    assert requested[0] == "2026-01"          # дыра до отметки загрузки
    assert "2026-02" not in requested and "2026-03" not in requested
    assert r.status == "success"

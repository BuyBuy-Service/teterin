"""Часть A: идемпотентность, сохранность ручных правок, битые файлы, недопустимые параметры (синтетические данные)."""
import zipfile

import pandas as pd

from db import connect
from sources import bts


def make_zip(path, rows):
    base = {c: None for c in bts.COLS}
    base.update(Year=2026, Month=8, FlightDate="2026-08-01", Reporting_Airline="UA", Origin="ORD", Dest="DEN",
                CRSDepTime=700, DepTime=705, DepDelay=5.0, DepDel15=0.0, Cancelled=0.0, Diverted=0.0)
    df = pd.DataFrame([{**base, **r} for r in rows])
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("On_Time_test.csv", df.to_csv(index=False))
    return path


ROWS = [
    {"Flight_Number_Reporting_Airline": 1},
    {"Flight_Number_Reporting_Airline": 2, "DepDelay": 40.0, "DepDel15": 1.0},
    {"Flight_Number_Reporting_Airline": 3, "Origin": "LAX", "Dest": "ORD"},   # прилёт в ORD
    {"Flight_Number_Reporting_Airline": 4, "Origin": "LAX", "Dest": "JFK"},   # не наш аэропорт
]


def count():
    with connect() as con:
        return con.execute("SELECT count(*) FROM flights").fetchone()[0]


def test_import_is_idempotent(tmp_path):
    z = make_zip(tmp_path / "m.zip", ROWS)
    r1 = bts.import_file(path=str(z))
    assert r1.status == "success" and r1.stats["rows_inserted"] == 3
    r2 = bts.import_file(path=str(z))
    assert r2.status == "success"
    assert r2.stats["rows_inserted"] == 0 and r2.stats["rows_updated"] == 0 and r2.stats["rows_skipped"] == 3
    assert count() == 3
    with connect() as con:
        assert con.execute("SELECT count(*) FROM raw_files").fetchone()[0] == 1
        assert con.execute("SELECT value FROM watermarks WHERE source='bts'").fetchone()[0] == "2026-08"
        assert con.execute("SELECT direction FROM flights WHERE flight_number=3").fetchone()[0] == "arrival"


def test_manual_edit_and_delete_survive_reload(tmp_path):
    z = make_zip(tmp_path / "m.zip", ROWS)
    bts.import_file(path=str(z))
    with connect() as con:
        con.execute("UPDATE flights SET dep_delay = 99, is_manual = 1 WHERE flight_number = 1")
        con.execute("UPDATE flights SET is_deleted = 1 WHERE flight_number = 2")
    # источник «исправил» данные по обоим рейсам
    rows = [dict(r) for r in ROWS]
    rows[0]["DepDelay"], rows[1]["DepDelay"] = 7.0, 41.0
    bts.import_file(path=str(make_zip(tmp_path / "m2.zip", rows)))
    with connect() as con:
        assert con.execute("SELECT dep_delay FROM flights WHERE flight_number=1").fetchone()[0] == 99
        assert con.execute("SELECT is_deleted, dep_delay FROM flights WHERE flight_number=2").fetchone()[:] == (1, 40)
    assert count() == 3


def test_source_update_is_applied(tmp_path):
    bts.import_file(path=str(make_zip(tmp_path / "a.zip", ROWS)))
    rows = [dict(r) for r in ROWS]
    rows[0]["DepDelay"] = 7.0
    r = bts.import_file(path=str(make_zip(tmp_path / "b.zip", rows)))
    assert r.stats["rows_updated"] == 1 and r.stats["rows_inserted"] == 0


def test_corrupt_file_goes_to_quarantine(tmp_path):
    bad = tmp_path / "bad.zip"
    bad.write_bytes(b"PK\x03\x04 definitely not a zip")
    r = bts.import_file(path=str(bad))
    assert r.status == "failed" and "карантин" in r.error
    assert count() == 0


def test_future_month_rejected():
    r = bts.ingest(month="2099-01")
    assert r.status == "failed" and "вне допустимого диапазона" in r.error
    r = bts.ingest(month="август")
    assert r.status == "failed" and "YYYY-MM" in r.error


def test_parallel_run_is_skipped():
    with connect() as con:
        con.execute("INSERT INTO load_log(job, started_at, status) VALUES ('bts', strftime('%Y-%m-%dT%H:%M:%SZ','now'), 'running')")
    r = bts.ingest(month="2026-01")
    assert r.status == "skipped"

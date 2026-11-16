"""Часть A: ручные правки — валидация, аудит, согласованность флага DepDel15, мягкое удаление."""
import pytest

import edits
from db import connect
from sources import bts
from tests.test_bts import ROWS, make_zip

KEY = dict(flight_date="2026-08-01", carrier="UA", flight_number=1, origin="ORD", dest="DEN", crs_dep_time=700)


@pytest.fixture
def loaded(tmp_path):
    bts.import_file(path=str(make_zip(tmp_path / "m.zip", ROWS)))


def row():
    with connect() as con:
        return con.execute("SELECT * FROM flights WHERE flight_number = 1").fetchone()


def test_edit_sets_manual_flag_recomputes_del15_and_logs(loaded):
    assert edits.update_flight(KEY, {"dep_delay": 45}, "Селиванова А.К.") == 2  # dep_delay + dep_del15
    r = row()
    assert (r["dep_delay"], r["dep_del15"], r["is_manual"]) == (45, 1, 1)
    with connect() as con:
        log = con.execute("SELECT field, old_value, new_value, user_name FROM edit_log ORDER BY id").fetchall()
    assert [tuple(x) for x in log] == [("dep_delay", "5.0", "45.0", "Селиванова А.К."), ("dep_del15", "0", "1", "Селиванова А.К.")]


def test_same_value_is_not_an_edit(loaded):
    assert edits.update_flight(KEY, {"dep_delay": 5}, "x") == 0
    assert row()["is_manual"] == 0


@pytest.mark.parametrize("field,value", [("dep_delay", "abc"), ("dep_delay", 99999), ("dep_time", 1275),
                                         ("cancelled", 2)])
def test_invalid_values_rejected(loaded, field, value):
    with pytest.raises(ValueError):
        edits.update_flight(KEY, {field: value}, "x")
    assert row()["is_manual"] == 0


def test_soft_delete_and_restore(loaded):
    assert edits.set_deleted([KEY], True, "x") == 1
    assert edits.set_deleted([KEY], True, "x") == 0  # повторно — ничего не меняет
    assert row()["is_deleted"] == 1
    assert edits.set_deleted([KEY], False, "x") == 1
    assert row()["is_deleted"] == 0

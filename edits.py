"""Ручные правки данных из интерфейса (часть A).

Правка ставит is_manual = 1 — повторная загрузка BTS такую запись не перезапишет.
Удаление мягкое (is_deleted = 1): запись остаётся в БД, её можно восстановить, повторная загрузка её не «воскресит».
Каждое изменение пишется в edit_log: кто, что, старое и новое значение.
"""
import math

from db import connect
from pipeline import now

KEY = ["flight_date", "carrier", "flight_number", "origin", "dest", "crs_dep_time"]

# поле -> (тип, минимум, максимум)
EDITABLE = {
    "dep_time": (int, 0, 2400), "arr_time": (int, 0, 2400),
    "dep_delay": (float, -120, 3000), "arr_delay": (float, -120, 3000),
    "cancelled": (int, 0, 1), "diverted": (int, 0, 1),
    "carrier_delay": (float, 0, 3000), "weather_delay": (float, 0, 3000), "nas_delay": (float, 0, 3000),
    "security_delay": (float, 0, 3000), "late_aircraft_delay": (float, 0, 3000),
}


def clean(field: str, value):
    """Проверка значения. Пустое -> NULL. Ошибка -> ValueError с понятным текстом."""
    if value is None or (isinstance(value, float) and math.isnan(value)) or value == "":
        return None
    typ, lo, hi = EDITABLE[field]
    try:
        v = typ(float(value)) if typ is int else typ(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field}: «{value}» — не число") from None
    if not lo <= v <= hi:
        raise ValueError(f"{field}: {v} вне допустимого диапазона {lo}…{hi}")
    if field.endswith("_time") and v % 100 >= 60:
        raise ValueError(f"{field}: {v} — неверное время hhmm")
    return v


def row_key(key: dict) -> str:
    return " ".join(str(key[k]) for k in KEY)


def update_flight(key: dict, changes: dict, user: str) -> int:
    """Применяет правки к одному рейсу. Флаги DepDel15/ArrDel15 пересчитываются из минут — чтобы данные
    оставались согласованными (это же проверяет DQ). Возвращает число изменённых полей."""
    changes = {f: clean(f, v) for f, v in changes.items()}
    where = " AND ".join(f"{k} = ?" for k in KEY)
    with connect() as con:
        old = con.execute(f"SELECT * FROM flights WHERE {where}", [key[k] for k in KEY]).fetchone()
        if old is None:
            raise ValueError(f"рейс не найден: {row_key(key)}")
        if "dep_delay" in changes:
            changes["dep_del15"] = None if changes["dep_delay"] is None else int(changes["dep_delay"] >= 15)
        if "arr_delay" in changes:
            changes["arr_del15"] = None if changes["arr_delay"] is None else int(changes["arr_delay"] >= 15)
        changes = {f: v for f, v in changes.items() if old[f] != v}
        if not changes:
            return 0
        sets = ", ".join(f"{f} = ?" for f in changes)
        con.execute(f"UPDATE flights SET {sets}, is_manual = 1, updated_at = ? WHERE {where}",
                    [*changes.values(), now(), *[key[k] for k in KEY]])
        con.executemany(
            "INSERT INTO edit_log(ts, user_name, table_name, row_key, field, old_value, new_value) VALUES (?,?,?,?,?,?,?)",
            [(now(), user, "flights", row_key(key), f, _s(old[f]), _s(v)) for f, v in changes.items()])
    return len(changes)


def set_deleted(keys: list[dict], deleted: bool, user: str) -> int:
    where = " AND ".join(f"{k} = ?" for k in KEY)
    n = 0
    with connect() as con:
        for key in keys:
            cur = con.execute(f"UPDATE flights SET is_deleted = ?, updated_at = ? WHERE {where} AND is_deleted = ?",
                              [int(deleted), now(), *[key[k] for k in KEY], int(not deleted)])
            if cur.rowcount:
                n += 1
                con.execute(
                    "INSERT INTO edit_log(ts, user_name, table_name, row_key, field, old_value, new_value) VALUES (?,?,?,?,?,?,?)",
                    (now(), user, "flights", row_key(key), "is_deleted", str(int(not deleted)), str(int(deleted))))
    return n


def _s(v):
    return None if v is None else str(v)

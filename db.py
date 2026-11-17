"""Подключение к SQLite и создание схемы."""
import sqlite3
import config


def connect() -> sqlite3.Connection:
    # config.DB_PATH читается при каждом вызове — тесты подменяют его на временную БД
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(config.DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA journal_mode = WAL")  # дашборд читает, пока идёт загрузка
    return con


# таблицы, которые полностью пересобираются при каждом запуске: при изменении схемы их можно просто пересоздать
REBUILT = {"forecast_weather": "station", "daily": "n_severe"}


def init_db() -> None:
    with connect() as con:
        for table, new_col in REBUILT.items():  # миграция: старая версия таблицы без новой колонки
            cols = [r[1] for r in con.execute(f"PRAGMA table_info({table})")]
            if cols and new_col not in cols:
                con.execute(f"DROP TABLE {table}")
        con.executescript((config.ROOT / "schema.sql").read_text(encoding="utf-8"))


if __name__ == "__main__":
    init_db()
    print("schema ok:", config.DB_PATH)

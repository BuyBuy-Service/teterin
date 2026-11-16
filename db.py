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


def init_db() -> None:
    with connect() as con:
        con.executescript((config.ROOT / "schema.sql").read_text(encoding="utf-8"))


if __name__ == "__main__":
    init_db()
    print("schema ok:", config.DB_PATH)

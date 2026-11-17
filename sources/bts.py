"""S1. BTS On-Time Performance (часть A).

Помесячный ZIP с CSV по всем рейсам США -> файл в data/raw/bts (+ sha256 в raw_files)
-> строки нашего аэропорта -> таблица flights.

Инкрементальность: watermark = последний загруженный месяц; запрашиваем только следующие,
пока BTS не ответит 404 («ещё не опубликован»).
Идемпотентность: файл с тем же sha256 не регистрируется повторно; рейсы — UPSERT по естественному ключу.
Ручные правки (is_manual) и удалённые записи (is_deleted) повторная загрузка не трогает.
"""
import hashlib
import io
import shutil
import zipfile
from datetime import date
from pathlib import Path

import pandas as pd

import config
from db import connect
from pipeline import fault, get_watermark, http_get, job, now, set_watermark

SOURCE = "bts"

# колонка BTS -> колонка flights
COLS = {
    "FlightDate": "flight_date", "Reporting_Airline": "carrier",
    "Flight_Number_Reporting_Airline": "flight_number", "Origin": "origin", "Dest": "dest",
    "CRSDepTime": "crs_dep_time", "DepTime": "dep_time", "DepDelay": "dep_delay", "DepDel15": "dep_del15",
    "CRSArrTime": "crs_arr_time", "ArrTime": "arr_time", "ArrDelay": "arr_delay", "ArrDel15": "arr_del15",
    "Cancelled": "cancelled", "CancellationCode": "cancellation_code", "Diverted": "diverted",
    "CarrierDelay": "carrier_delay", "WeatherDelay": "weather_delay", "NASDelay": "nas_delay",
    "SecurityDelay": "security_delay", "LateAircraftDelay": "late_aircraft_delay", "Tail_Number": "tail_number",
}
KEY = ["flight_date", "carrier", "flight_number", "origin", "dest", "crs_dep_time"]
INT_COLS = ["flight_number", "crs_dep_time", "dep_time", "dep_del15", "crs_arr_time", "arr_time",
            "arr_del15", "cancelled", "diverted"]
FIELDS = list(COLS.values()) + ["direction"]
DATA_FIELDS = [c for c in FIELDS if c not in KEY]


def month_add(period: str, k: int) -> str:
    y, m = map(int, period.split("-"))
    n = y * 12 + m - 1 + k
    return f"{n // 12}-{n % 12 + 1:02d}"


def parse_period(value: str) -> str:
    """Проверка параметра ручного запуска: 'YYYY-MM', не раньше 1987-10 и не в будущем."""
    try:
        y, m = map(int, value.split("-"))
        p = f"{y}-{m:02d}"
        date(y, m, 1)
    except (ValueError, AttributeError):
        raise ValueError(f"месяц должен быть в формате YYYY-MM, получено: {value!r}") from None
    if p < "1987-10" or p > date.today().strftime("%Y-%m"):
        raise ValueError(f"месяц {p} вне допустимого диапазона (1987-10 .. текущий)")
    return p


@job("bts", SOURCE)
def ingest(run, month: str | None = None):
    """Без параметров — догрузить все недостающие месяцы от начала истории (config.HISTORY_START) до текущего:
    новые месяцы после watermark и «дыры» до него (например, если историю удлинили в конфиге).
    month='YYYY-MM' — (пере)загрузить конкретный месяц."""
    if month:
        periods = [parse_period(month)]
    else:
        with connect() as con:
            loaded = {r[0] for r in con.execute("SELECT DISTINCT period FROM raw_files WHERE source = ?", (SOURCE,))}
        last = date.today().strftime("%Y-%m")
        periods, p = [], config.HISTORY_START.strftime("%Y-%m")
        while p <= last:
            if p not in loaded:
                periods.append(p)
            p = month_add(p, 1)
    if not periods:
        run.note("новых месяцев нет")
    wm = get_watermark(SOURCE)
    for p in periods:
        path = download(run, p)
        if path is None:
            if wm is None or p > wm:  # после последнего загруженного — дальше тем более не опубликовано
                run.note(f"{p}: ещё не опубликован в BTS")
                break
            run.note(f"{p}: нет на сайте BTS")  # дыра в прошлом — пропускаем, идём дальше
            continue
        load_zip(run, path, url=config.BTS_URL.format(year=int(p[:4]), month=int(p[5:])))


@job("bts_import", SOURCE)
def import_file(run, path: str):
    """Ручной импорт ZIP (из UI) — запасной путь, если скачивание скриптом недоступно."""
    src = Path(path)
    dst = config.RAW_DIR / "bts" / f"manual_{src.name}"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)
    load_zip(run, dst, url=None)


def download(run, period: str) -> Path | None:
    y, m = int(period[:4]), int(period[5:])
    url = config.BTS_URL.format(year=y, month=m)
    print(f"  BTS {period}: скачиваю…")
    resp = http_get(url, run, stream=True)
    if resp.status_code == 404:
        return None
    folder = config.RAW_DIR / "bts"
    folder.mkdir(parents=True, exist_ok=True)
    tmp = folder / f"{period}.part"
    with open(tmp, "wb") as f:
        for chunk in resp.iter_content(1 << 20):
            f.write(chunk)
    if fault() == "corrupt_bts_file":  # демо: файл «побился» при передаче
        tmp.write_bytes(tmp.read_bytes()[:100_000])
    sha = hashlib.sha256(tmp.read_bytes()).hexdigest()
    path = folder / f"{period}_{sha[:8]}.zip"  # raw-файлы не перезаписываются: новая версия = новое имя
    tmp.replace(path)
    return path


def read_zip(path: Path) -> pd.DataFrame:
    """Читает CSV из ZIP. Битый файл -> перенос в data/raw/quarantine и понятная ошибка."""
    try:
        with zipfile.ZipFile(path) as z:
            name = next(n for n in z.namelist() if n.lower().endswith(".csv"))
            with z.open(name) as f:
                df = pd.read_csv(f, usecols=["Year", "Month", *COLS], low_memory=False,
                                 dtype={"Tail_Number": str, "CancellationCode": str})
    except (zipfile.BadZipFile, StopIteration, ValueError, KeyError, EOFError) as e:
        q = config.RAW_DIR / "quarantine"
        q.mkdir(parents=True, exist_ok=True)
        shutil.move(path, q / path.name)
        raise ValueError(f"битый файл {path.name} перенесён в карантин: {type(e).__name__} {e}") from None
    return df


def prepare(df: pd.DataFrame) -> pd.DataFrame:
    ap = config.AIRPORT_IATA
    df = df[(df["Origin"] == ap) | (df["Dest"] == ap)].rename(columns=COLS)
    df = df.assign(direction=(df["origin"] == ap).map({True: "departure", False: "arrival"}))
    for c in INT_COLS:
        df[c] = pd.to_numeric(df[c], errors="coerce").round().astype("Int64")
    df = df[FIELDS]
    return df.astype(object).where(df.notna(), None)  # NaN -> NULL


def load_zip(run, path: Path, url: str | None):
    raw = read_zip(path)
    period = f"{int(raw['Year'].iloc[0])}-{int(raw['Month'].iloc[0]):02d}"
    df = prepare(raw)
    run.add(rows_fetched=len(df))
    dup = df.duplicated(KEY)
    if dup.any():
        run.note(f"{period}: дубли ключа в исходнике: {int(dup.sum())}")
        run.add(rows_skipped=int(dup.sum()))
        df = df[~dup]
    sha = hashlib.sha256(path.read_bytes()).hexdigest()

    con = connect()
    try:
        with con:  # одна транзакция: raw_files + flights + watermark
            con.execute(
                """INSERT OR IGNORE INTO raw_files(source, period, url, sha256, size, path, loaded_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (SOURCE, period, url, sha, path.stat().st_size, str(path), now()))
            file_id = con.execute("SELECT id FROM raw_files WHERE source = ? AND sha256 = ?",
                                  (SOURCE, sha)).fetchone()[0]
            ins, upd, protected = upsert_flights(con, df, file_id)
            set_watermark(con, SOURCE, period)
    finally:
        con.close()
    run.add(rows_inserted=ins, rows_updated=upd, rows_skipped=len(df) - ins - upd)
    print(f"  BTS {period}: строк {len(df)}, новых {ins}, обновлено {upd}, защищено ручных правок {protected}")


def upsert_flights(con, df: pd.DataFrame, file_id: int) -> tuple[int, int, int]:
    cols = ", ".join(FIELDS)
    con.execute("DROP TABLE IF EXISTS temp.stage")
    con.execute(f"CREATE TEMP TABLE stage AS SELECT {cols} FROM flights WHERE 0")
    con.executemany(f"INSERT INTO stage VALUES ({', '.join('?' * len(FIELDS))})",
                    df.itertuples(index=False, name=None))
    on_key = " AND ".join(f"f.{k} = s.{k}" for k in KEY)
    ts = now()

    # записи, которые вручную правили или удаляли — не трогаем
    protected = con.execute(
        f"SELECT count(*) FROM stage s JOIN flights f ON {on_key} WHERE f.is_manual = 1 OR f.is_deleted = 1"
    ).fetchone()[0]

    # обновляем только реально изменившиеся строки (иначе повторный запуск «обновлял» бы всё)
    before = con.total_changes
    on_key_upd = " AND ".join(f"flights.{k} = s.{k}" for k in KEY)
    con.execute(
        f"""UPDATE flights SET {', '.join(f'{c} = s.{c}' for c in DATA_FIELDS)}, file_id = ?, updated_at = ?
            FROM stage s WHERE {on_key_upd} AND flights.is_manual = 0 AND flights.is_deleted = 0
            AND ({' OR '.join(f'flights.{c} IS NOT s.{c}' for c in DATA_FIELDS)})""",
        (file_id, ts))
    updated = con.total_changes - before

    before = con.total_changes
    con.execute(f"INSERT OR IGNORE INTO flights ({cols}, file_id, updated_at) SELECT {cols}, ?, ? FROM stage",
                (file_id, ts))
    inserted = con.total_changes - before
    con.execute("DROP TABLE temp.stage")
    return inserted, updated, protected

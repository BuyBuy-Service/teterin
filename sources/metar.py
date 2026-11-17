"""S2. METAR через Iowa Environmental Mesonet (часть B).

METAR — сырой текст погодной сводки аэропорта, например
    KORD 140251Z 33013G20KT 3SM -SN BR OVC008 02/M04 A3010
Это слабоструктурированные данные (текст + показания датчиков). Здесь только сбор: текст как есть -> raw_metar.
Разбор текста в признаки — metar_parser.py.

Инкрементальность: watermark = время последней сводки; следующий запуск берёт данные с перекрытием 2 часа
(сводки иногда публикуются с опозданием). Дубли отсекает первичный ключ (station, время, текст).
Запросы — кусками по месяцу: IEM ограничивает частоту по IP и под нагрузкой отвечает 503.
"""
import csv
import io
import time
from datetime import date, datetime, timedelta, timezone

import config
from db import connect
from pipeline import SourceError, get_watermark, http_get, job, now, set_watermark

SOURCE = "metar"
NETWORK_SOURCE = "metar_network"
OVERLAP = timedelta(hours=2)


def next_month(d: date) -> date:
    return date(d.year + d.month // 12, d.month % 12 + 1, 1)


@job("metar", SOURCE)
def ingest(run, start: str | None = None, end: str | None = None):
    """Сводки аэропорта. start/end — 'YYYY-MM-DD' (end не включается).
    По умолчанию: от watermark (или начала истории) до сегодня."""
    load_range(run, SOURCE, [config.AIRPORT_IATA], start, end)


@job("metar_network", NETWORK_SOURCE)
def ingest_network(run, start: str | None = None, end: str | None = None):
    """Сводки аэропортов сети (config.NETWORK) — куда летит больше всего рейсов. Своя отметка загрузки."""
    if config.NETWORK:
        load_range(run, NETWORK_SOURCE, sorted(config.NETWORK), start, end)
    else:
        run.note("сеть не задана")


def load_range(run, source: str, stations: list[str], start: str | None, end: str | None):
    today = datetime.now(timezone.utc).date()
    if start:
        d0 = date.fromisoformat(start)
    else:
        wm = get_watermark(source)
        d0 = (datetime.fromisoformat(wm) - OVERLAP).date() if wm else config.HISTORY_START
    d1 = date.fromisoformat(end) if end else today + timedelta(days=1)
    if d1 > today + timedelta(days=1):
        raise ValueError(f"нельзя загрузить METAR из будущего: end={d1}")
    if d0 >= d1:
        raise ValueError(f"пустой период: {d0} .. {d1}")

    ranges = [(d0, d1)]
    if not start:  # история удлинилась (config.HISTORY_START раньше самой ранней сводки) — догружаем и её
        with connect() as con:
            first = con.execute(f"SELECT min(observed_at_utc) FROM raw_metar WHERE station IN "
                                f"({','.join('?' * len(stations))})", stations).fetchone()[0]
        if first and date.fromisoformat(first[:10]) > config.HISTORY_START:
            ranges.insert(0, (config.HISTORY_START, date.fromisoformat(first[:10]) + timedelta(days=1)))
    for a, b in ranges:
        cur = a
        while cur < b:
            nxt = min(next_month(cur), b)
            load_chunk(run, cur, nxt, stations, source)
            cur = nxt
            time.sleep(1)  # вежливость к IEM


def load_chunk(run, d0: date, d1: date, stations: list[str] | None = None, source: str = SOURCE):
    stations = stations or [config.AIRPORT_IATA]
    resp = http_get(config.IEM_URL, run, params={
        "station": stations, "data": "metar", "tz": "Etc/UTC", "format": "onlycomma",
        "latlon": "no", "missing": "empty", "report_type": [3, 4],  # 3 — регулярные, 4 — внеочередные (SPECI)
        "year1": d0.year, "month1": d0.month, "day1": d0.day,
        "year2": d1.year, "month2": d1.month, "day2": d1.day})
    if resp.status_code == 404 or not resp.text.startswith("station"):
        raise SourceError(f"IEM вернул неожиданный ответ: {resp.text[:200]!r}")
    rows = [(r["station"], r["valid"], r["metar"].strip(), now())
            for r in csv.DictReader(io.StringIO(resp.text)) if r.get("metar")]
    run.add(rows_fetched=len(rows))
    with connect() as con:  # данные и watermark — одной транзакцией
        before = con.total_changes
        con.executemany("INSERT OR IGNORE INTO raw_metar VALUES (?,?,?,?)", rows)
        ins = con.total_changes - before
        if rows:
            set_watermark(con, source, max(r[1] for r in rows))
    run.add(rows_inserted=ins, rows_skipped=len(rows) - ins)
    print(f"  METAR {'+'.join(stations) if len(stations) < 4 else f'{len(stations)} станций'} {d0}..{d1}: "
          f"сводок {len(rows)}, новых {ins}")

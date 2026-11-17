"""Общая обвязка загрузок (часть A).

- Run / @job — каждый запуск джобы пишет строку в журнал load_log (параметры, счётчики, статус, ошибка).
- Защита от параллельного запуска одной и той же джобы.
- Ошибка одной джобы не валит остальные: исключение ловится и пишется в журнал как failed/partial.
- watermarks — докуда загружен источник (основа инкрементальности).
- http_get — HTTP с таймаутом и ретраями (экспоненциальная пауза, учёт Retry-After на 429/5xx).
- AERO_FAULT — демо-режим сбоев для защиты: timeout | rate_limit_429 | corrupt_bts_file.

Запуск всех джоб:  python pipeline.py [--only bts metar openmeteo dq] [--trigger manual|schedule|backfill]
"""
import argparse
import functools
import json
import os
import random
import time
from datetime import datetime, timedelta, timezone

import requests

import config
from db import connect, init_db

LOCK_WINDOW = timedelta(hours=2)  # «running» старше этого считаем зависшим запуском
RETRY_STATUSES = {429, 500, 502, 503, 504}


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fault() -> str:
    return os.getenv("AERO_FAULT", "none")


class SourceError(Exception):
    """Источник недоступен после всех попыток или вернул мусор."""


# ---------- watermarks ----------

def get_watermark(source: str) -> str | None:
    with connect() as con:
        row = con.execute("SELECT value FROM watermarks WHERE source = ?", (source,)).fetchone()
    return row[0] if row else None


def set_watermark(con, source: str, value: str) -> None:
    """Вызывается внутри той же транзакции, что и запись данных: либо сдвинулось и то, и другое, либо ничего.
    Watermark только растёт."""
    con.execute(
        """INSERT INTO watermarks(source, value, updated_at) VALUES (?, ?, ?)
           ON CONFLICT(source) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
           WHERE excluded.value > watermarks.value""",
        (source, value, now()))


# ---------- журнал запусков ----------

class Run:
    COUNTERS = ("rows_fetched", "rows_inserted", "rows_updated", "rows_skipped", "http_calls", "retries")

    def __init__(self, job: str, source: str, params: dict, trigger: str):
        self.job, self.source, self.params, self.trigger = job, source, params, trigger
        self.stats = dict.fromkeys(self.COUNTERS, 0)
        self.notes: list[str] = []
        self.status = "running"
        self.error = None

    def add(self, **counters):
        for k, v in counters.items():
            self.stats[k] += int(v)

    def note(self, text: str):
        """Нефатальное замечание (например, «месяц ещё не опубликован») — попадёт в поле error журнала."""
        self.notes.append(text)
        print("  ·", text)

    def start(self) -> bool:
        """Создаёт запись в журнале. Возвращает False, если такая же джоба уже выполняется."""
        self.wm_before = get_watermark(self.source)
        started = datetime.now(timezone.utc)
        with connect() as con:
            busy = con.execute(
                "SELECT id FROM load_log WHERE job = ? AND status = 'running' AND started_at > ?",
                (self.job, (started - LOCK_WINDOW).strftime("%Y-%m-%dT%H:%M:%SZ"))).fetchone()
            self.id = con.execute(
                "INSERT INTO load_log(job, params, trigger, started_at, watermark_before) VALUES (?,?,?,?,?)",
                (self.job, json.dumps(self.params, ensure_ascii=False, default=str), self.trigger,
                 now(), self.wm_before)).lastrowid
        self._t0 = time.monotonic()
        return busy is None

    def finish(self, status: str | None = None, error: Exception | str | None = None):
        if isinstance(error, Exception):
            # что-то успели записать до сбоя -> partial, иначе failed
            done = self.stats["rows_inserted"] + self.stats["rows_updated"]
            self.status = status or ("partial" if done else "failed")
            self.error = f"{type(error).__name__}: {error}"
        else:
            self.status = status or "success"
            self.error = error
        if self.notes:
            self.error = "; ".join(filter(None, [self.error, *self.notes]))
        self.wm_after = get_watermark(self.source)
        sets = ", ".join(f"{k} = :{k}" for k in self.COUNTERS)
        with connect() as con:
            con.execute(
                f"""UPDATE load_log SET finished_at = :fin, status = :status, error = :error,
                    watermark_after = :wm, {sets} WHERE id = :id""",
                dict(self.stats, fin=now(), status=self.status, error=self.error, wm=self.wm_after, id=self.id))
        s = self.stats
        print(f"[{self.job}] {self.status}: fetched={s['rows_fetched']} inserted={s['rows_inserted']} "
              f"updated={s['rows_updated']} skipped={s['rows_skipped']} http={s['http_calls']} "
              f"retries={s['retries']} {round(time.monotonic() - self._t0, 1)}s"
              + (f" | {self.error}" if self.error else ""))


def job(name: str, source: str | None = None):
    """Декоратор джобы: fn(run, **params). Возвращает Run с итогом — исключения наружу не летят."""
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(trigger: str = "manual", **params) -> Run:
            run = Run(name, source or name, params, trigger)
            if not run.start():
                run.finish("skipped", "уже выполняется другой запуск этой джобы")
                return run
            try:
                fn(run, **params)
                run.finish()
            except Exception as e:  # noqa: BLE001 — любая ошибка джобы фиксируется в журнале
                run.finish(error=e)
            return run
        return wrapper
    return deco


# ---------- HTTP ----------

def http_get(url: str, run: Run | None = None, params=None, **kwargs) -> requests.Response:
    """GET с таймаутом и ретраями. 404 возвращается вызывающему (у BTS это «месяц не опубликован»)."""
    for attempt in range(1, config.HTTP_RETRIES + 1):
        if run:
            run.add(http_calls=1)
        retry_after = None
        try:
            if fault() == "timeout":
                raise requests.Timeout("AERO_FAULT=timeout (имитация)")
            if fault() == "rate_limit_429" and attempt <= 2:
                status, retry_after = 429, "2"  # имитация: две попытки упираются в лимит, третья проходит
            else:
                resp = requests.get(url, params=params, timeout=config.HTTP_TIMEOUT,
                                    headers={"User-Agent": config.USER_AGENT}, **kwargs)
                status, retry_after = resp.status_code, resp.headers.get("Retry-After")
                if status < 400 or status == 404:
                    return resp
                if status not in RETRY_STATUSES:
                    resp.raise_for_status()  # прочие 4xx повторять бессмысленно
            err = f"HTTP {status}"
        except (requests.ConnectionError, requests.Timeout) as e:
            err = type(e).__name__
        if attempt == config.HTTP_RETRIES:
            raise SourceError(f"{url}: {err}, попыток: {attempt}")
        delay = float(retry_after) if retry_after and retry_after.isdigit() else 2 ** attempt + random.random()
        if run:
            run.add(retries=1)
        print(f"  retry {attempt}/{config.HTTP_RETRIES - 1}: {err}, пауза {delay:.0f} с")
        time.sleep(delay)


# ---------- запуск цепочки ----------

def jobs() -> dict:
    from sources import bts, metar, openmeteo
    import dq
    import marts
    import metar_parser
    import model
    return {"bts": bts.ingest, "metar": metar.ingest, "metar_network": metar.ingest_network,
            "openmeteo": openmeteo.ingest,
            "weather": metar_parser.transform, "marts": marts.build, "model": model.train_and_predict,
            "dq": dq.run}


def main():
    all_jobs = jobs()
    ap = argparse.ArgumentParser(description="AeroPulse: загрузка и обработка данных")
    ap.add_argument("--only", nargs="+", choices=list(all_jobs), help="какие джобы запустить (по умолчанию все)")
    ap.add_argument("--trigger", default="manual", choices=["manual", "schedule", "backfill"])
    args = ap.parse_args()
    init_db()
    for name in args.only or all_jobs:
        all_jobs[name](trigger=args.trigger)


if __name__ == "__main__":
    main()

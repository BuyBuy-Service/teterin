"""Часть B: инкрементальная и идемпотентная загрузка METAR (ответ IEM подменён)."""
import pipeline
from db import connect
from sources import metar

CSV = """station,valid,metar
ORD,2026-11-14 00:51,KORD 140051Z 33008KT 10SM FEW043 SCT070 03/M04 A3009 RMK AO2
ORD,2026-11-14 01:51,KORD 140151Z 32009KT 10SM SCT050 02/M04 A3010 RMK AO2
ORD,2026-11-14 02:51,KORD 140251Z 33013G20KT 10SM FEW050 02/M04 A3010 RMK AO2
"""


class Resp:
    status_code = 200
    text = CSV


def test_metar_reload_adds_nothing(monkeypatch):
    calls = []
    monkeypatch.setattr(metar, "http_get", lambda url, run, params: calls.append(params) or Resp())
    r1 = metar.ingest(start="2026-11-14", end="2026-11-15")
    assert r1.status == "success" and r1.stats["rows_inserted"] == 3
    r2 = metar.ingest(start="2026-11-14", end="2026-11-15")
    assert r2.stats["rows_inserted"] == 0 and r2.stats["rows_skipped"] == 3
    assert pipeline.get_watermark("metar") == "2026-11-14 02:51"


def test_metar_incremental_starts_from_watermark(monkeypatch):
    calls = []
    monkeypatch.setattr(metar, "http_get", lambda url, run, params: calls.append(params) or Resp())
    metar.ingest(start="2026-11-14", end="2026-11-15")
    calls.clear()
    metar.ingest(end="2026-11-16")
    # watermark 14.11 02:51 минус 2 ч перекрытия -> запрос начинается с 14.11, а не с начала истории
    assert (calls[0]["year1"], calls[0]["month1"], calls[0]["day1"]) == (2026, 11, 14)


def test_metar_future_rejected():
    r = metar.ingest(start="2026-01-01", end="2099-01-01")
    assert r.status == "failed" and "будущего" in r.error
    with connect() as con:
        assert con.execute("SELECT count(*) FROM raw_metar").fetchone()[0] == 0

"""Разбор METAR-текста в признаки (часть B).

Пример: KORD 161451Z 27015G25KT 3SM -SN BR OVC008 M02/M04 A2990 RMK ...
  27015G25KT — ветер 270°, 15 узлов, порывы 25;  3SM — видимость 3 мили;  -SN BR — слабый снег, дымка;
  OVC008 — сплошная облачность на 800 футах (это «потолок»);  M02/M04 — температура −2, точка росы −4.

Числа (ветер, видимость, облачность, температура) разбирает библиотека `metar`.
Погодные явления (снег, гроза, ледяной дождь, туман) — собственный разбор токенов: так прозрачнее и
не зависит от тонкостей библиотеки. Категория полётных условий — по правилам FAA (видимость + потолок).
"""
import warnings

from metar import Metar

from db import connect
from pipeline import job

# библиотека предупреждает о каждой нераспознанной группе (например, нестандартные ремарки) — это шум
warnings.filterwarnings("ignore", category=RuntimeWarning, module="metar")

# двухбуквенные коды явлений METAR
DESCRIPTORS = {"MI", "PR", "BC", "DR", "BL", "SH", "TS", "FZ"}
PRECIP = {"DZ", "RA", "SN", "SG", "IC", "PL", "GR", "GS", "UP"}
OBSCUR = {"BR", "FG", "FU", "VA", "DU", "SA", "HZ", "PY"}
OTHER = {"PO", "SQ", "FC", "SS", "DS"}
CODES = DESCRIPTORS | PRECIP | OBSCUR | OTHER


def weather_tokens(raw: str) -> list[str]:
    """Токены погодных явлений из основной части сводки (до RMK). VC (явление в окрестности) — не учитываем."""
    body = raw.split(" RMK")[0].split()[2:]  # без кода станции и времени
    out = []
    for tok in body:
        t = tok.lstrip("+-")
        if not t or t.startswith("VC") or len(t) % 2:
            continue
        parts = [t[i:i + 2] for i in range(0, len(t), 2)]
        if all(p in CODES for p in parts):
            out.append(tok)
    return out


def phenomena(raw: str) -> dict:
    toks = weather_tokens(raw)
    joined = " ".join(toks)
    has = lambda *codes: int(any(c in joined for c in codes))  # noqa: E731
    return {
        "precip": has(*PRECIP),
        "rain": has("RA", "DZ"),
        "snow": has("SN", "SG"),
        "fzra": int(any("FZ" in t and ("RA" in t or "DZ" in t) for t in toks)),
        "ts": has("TS"),
        "fog": has("FG"),
        "mist": has("BR"),
    }


def flight_category(vis_sm, ceiling_ft) -> str | None:
    """FAA: LIFR < 1 мили или потолок < 500 футов; IFR < 3 / < 1000; MVFR ≤ 5 / ≤ 3000; иначе VFR."""
    if vis_sm is None and ceiling_ft is None:
        return None
    v = vis_sm if vis_sm is not None else 99
    c = ceiling_ft if ceiling_ft is not None else 99999
    if v < 1 or c < 500:
        return "LIFR"
    if v < 3 or c < 1000:
        return "IFR"
    if v <= 5 or c <= 3000:
        return "MVFR"
    return "VFR"


def parse(raw: str, year: int, month: int) -> dict:
    """Возвращает признаки сводки. Если библиотека не справилась — parse_ok=0, но явления всё равно извлекаем."""
    res = {"temp_c": None, "wind_kt": None, "gust_kt": None, "vis_sm": None, "ceiling_ft": None, "parse_ok": 0}
    res.update(phenomena(raw))
    try:
        m = Metar.Metar(raw, month=month, year=year, strict=False)
    except Exception:  # noqa: BLE001 — сводки бывают с опечатками, это ожидаемо
        return res | {"flight_cat": None}
    res["temp_c"] = m.temp.value("C") if m.temp else None
    res["wind_kt"] = m.wind_speed.value("KT") if m.wind_speed else None
    res["gust_kt"] = m.wind_gust.value("KT") if m.wind_gust else None
    res["vis_sm"] = m.vis.value("SM") if m.vis else None
    ceilings = [h.value("FT") for cover, h, _ in m.sky if cover in ("BKN", "OVC", "VV") and h is not None]
    res["ceiling_ft"] = min(ceilings) if ceilings else None
    res["flight_cat"] = flight_category(res["vis_sm"], res["ceiling_ft"])
    res["parse_ok"] = int(res["wind_kt"] is not None or res["vis_sm"] is not None)
    return res


FIELDS = ["temp_c", "wind_kt", "gust_kt", "vis_sm", "ceiling_ft", "precip", "rain", "snow", "fzra",
          "ts", "fog", "mist", "flight_cat", "parse_ok"]


@job("weather_transform", "weather_transform")
def transform(run, full: bool = False):
    """raw_metar -> weather_obs. Инкрементально: разбираем только сводки, которых ещё нет в weather_obs.
    Если на один момент есть несколько текстов (исправленная сводка COR), берём последний полученный."""
    with connect() as con:
        if full:
            con.execute("DELETE FROM weather_obs")
        rows = con.execute(
            """SELECT r.station, r.observed_at_utc, r.raw_text FROM raw_metar r
               WHERE NOT EXISTS (SELECT 1 FROM weather_obs w
                                 WHERE w.station = r.station AND w.observed_at_utc = r.observed_at_utc)
               ORDER BY r.observed_at_utc, r.fetched_at""").fetchall()
        run.add(rows_fetched=len(rows))
        out = []
        for st, ts, raw in rows:
            p = parse(raw, int(ts[:4]), int(ts[5:7]))
            out.append((st, ts, raw, *(p[f] for f in FIELDS)))
        con.executemany(f"INSERT OR REPLACE INTO weather_obs VALUES ({', '.join('?' * (3 + len(FIELDS)))})", out)
    bad = sum(1 for r in out if not r[-1])
    run.add(rows_inserted=len(out))
    if bad:
        run.note(f"не разобрано сводок: {bad} из {len(out)}")

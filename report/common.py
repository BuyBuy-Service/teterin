"""Общее для отчёта и презентации: цифры из БД и подготовка картинок."""
import json
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image

HERE = Path(__file__).parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
import config  # noqa: E402

IMG = HERE / "img"
TRIM = HERE / "img_trim"
TRIM.mkdir(exist_ok=True)


def trimmed(name: str, pad: int = 12) -> Path:
    """Обрезает пустой фон снизу и справа у скриншота (фон Streamlit почти однотонный)."""
    src = IMG / f"{name}.png"
    im = Image.open(src).convert("RGB")
    a = np.asarray(im).astype(int)
    bg = a[-1, -1]
    diff = np.abs(a - bg).sum(axis=2) > 30
    rows, cols = np.where(diff.any(axis=1))[0], np.where(diff.any(axis=0))[0]
    box = (0, 0, min(im.width, cols.max() + pad), min(im.height, rows.max() + pad))
    out = TRIM / f"{name}.png"
    im.crop(box).save(out)
    return out


def facts() -> dict:
    con = sqlite3.connect(config.DB_PATH)
    q = lambda s, p=(): pd.read_sql(s, con, params=p)  # noqa: E731
    f = {}
    fl = q("""SELECT count(*) n, sum(direction='departure') dep, min(flight_date) a, max(flight_date) b,
                     count(DISTINCT carrier) carriers FROM flights WHERE is_deleted = 0""").iloc[0]
    f.update(flights=int(fl.n), departures=int(fl.dep), date_from=fl.a, date_to=fl.b, carriers=int(fl.carriers))
    w = q("SELECT count(*) n, sum(parse_ok) ok FROM weather_obs").iloc[0]
    f.update(metar=int(w.n), metar_ok=int(w.ok))
    d = q("SELECT avg(dep_flown) flown, sum(dep_del15_share*dep_flown)/sum(dep_flown) share FROM daily WHERE dep_flown IS NOT NULL").iloc[0]
    f.update(avg_flown=float(d.flown), del15=float(d.share))
    run = q("SELECT * FROM model_runs ORDER BY trained_at DESC LIMIT 1").iloc[0]
    f["metrics"] = json.loads(run.metrics_json)
    f["importance"] = json.loads(run.importance_json)
    f["model_version"] = run.model_version
    c = q("""SELECT sum(min_carrier) carrier, sum(min_late_aircraft) late, sum(min_nas) nas,
                    sum(min_weather) weather, sum(min_security) security FROM daily""").iloc[0]
    tot = c.sum()
    f["causes"] = {k: float(v / tot) for k, v in c.items()}
    f["dq"] = q("SELECT rule, severity, checked, failed FROM dq_log WHERE run_id = (SELECT max(run_id) FROM dq_log)")
    f["bts_wm"] = q("SELECT value FROM watermarks WHERE source='bts'").value[0]
    con.close()
    return f


def fmt(x, digits=0) -> str:
    s = f"{x:,.{digits}f}".replace(",", " ")
    return s.replace(".", ",")

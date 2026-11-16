"""Настройки проекта. Аэропорт и пути задаются здесь (или через переменные окружения), не в коде."""
import os
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("AERO_DATA_DIR", ROOT / "data"))
RAW_DIR = DATA_DIR / "raw"
DB_PATH = Path(os.getenv("AERO_DB", DATA_DIR / "aeropulse.db"))

# Аэропорт
AIRPORT_IATA = os.getenv("AERO_IATA", "ORD")      # код в BTS и IEM
AIRPORT_ICAO = os.getenv("AERO_ICAO", "KORD")     # код в METAR
AIRPORT_TZ = os.getenv("AERO_TZ", "America/Chicago")
AIRPORT_LAT = float(os.getenv("AERO_LAT", "41.9786"))
AIRPORT_LON = float(os.getenv("AERO_LON", "-87.9048"))

# Глубина начальной загрузки истории: 24 месяца BTS. BTS публикуется с лагом ~2 мес.,
# поэтому история начинается за (24 + 2) месяцев до текущего. Дальше всё решают watermarks.
BACKFILL_MONTHS = int(os.getenv("AERO_BACKFILL_MONTHS", "24"))
BTS_LAG_MONTHS = 2


def _history_start() -> date:
    if os.getenv("AERO_HISTORY_START"):
        return date.fromisoformat(os.getenv("AERO_HISTORY_START"))
    t = date.today()
    k = t.year * 12 + (t.month - 1) - (BACKFILL_MONTHS + BTS_LAG_MONTHS)
    return date(k // 12, k % 12 + 1, 1)


HISTORY_START = _history_start()

# HTTP
USER_AGENT = "aeropulse-student-project/0.1 (educational, MISIS)"
HTTP_TIMEOUT = 60
HTTP_RETRIES = 4

# URL источников
BTS_URL = ("https://transtats.bts.gov/PREZIP/"
           "On_Time_Reporting_Carrier_On_Time_Performance_1987_present_{year}_{month}.zip")
IEM_URL = "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py"
OPENMETEO_URL = "https://api.open-meteo.com/v1/forecast"

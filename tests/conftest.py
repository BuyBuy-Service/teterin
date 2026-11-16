import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
import db  # noqa: E402


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    """Каждый тест — на чистой временной БД; паузы между ретраями отключены."""
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(config, "RAW_DIR", tmp_path / "raw")
    monkeypatch.setattr("time.sleep", lambda s: None)
    monkeypatch.delenv("AERO_FAULT", raising=False)
    db.init_db()
    return tmp_path

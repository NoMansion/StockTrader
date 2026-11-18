import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.ledger import Ledger  # noqa: E402


@pytest.fixture
def ledger(tmp_path):
    led = Ledger(tmp_path / "pmt.db")
    yield led
    led.close()


@pytest.fixture
def market():
    return {"market_id": "m1", "question": "Will X happen by June 30?", "rules": "Resolves YES if X.",
            "event_id": "e1", "event_title": "X", "category": "politics", "end_ts": 2_000_000_000.0,
            "yes_token": "m1-yes", "no_token": "m1-no"}

"""The Sharadar ticker master download (src/providers_sharadar.fetch_tickers): table labels and broken downloads.

2026-11-25: Sharadar renamed its table labels ("SF1" -> "fundamentals"); the old filter kept 0 rows, the empty master
was cached, no name had fundamentals and the run chose 0 stocks."""
import io
import zipfile

import pandas as pd
import pytest

from src import providers_sharadar as ps

COLS = ["table", "permaticker", "ticker", "isdelisted", "lastpricedate"]


def _bulk(rows: list[tuple]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("tickers.csv", pd.DataFrame(rows, columns=COLS).to_csv(index=False))
    return buf.getvalue()


class _Resp:
    def __init__(self, status=200, content=b"", location=None):
        self.status_code, self.content, self.headers = status, content, {"Location": location} if location else {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


@pytest.fixture
def server(monkeypatch):
    """Fake Sharadar: the API answers with a redirect, the redirect serves `server["zip"]`."""
    state = {"zip": b"", "downloads": 0}

    def get(url, params=None, headers=None, allow_redirects=True, timeout=None):
        if url.endswith("/data/tickers"):
            return _Resp(302, location="https://bulk.example/tickers.zip")
        state["downloads"] += 1
        return _Resp(200, state["zip"])
    monkeypatch.setattr(ps.requests, "get", get)
    monkeypatch.setenv("SHARADAR_API_KEY", "test-key")
    monkeypatch.setattr(ps, "MIN_TICKERS", 3)
    return state


def _rows(label: str, n: int = 3) -> list[tuple]:
    return [(label, i, f"T{i}", "N", "2026-11-25") for i in range(n)]


@pytest.mark.parametrize("label", ["SF1", "fundamentals"])
def test_old_and_new_fundamentals_labels_are_kept(server, tmp_path, label):
    server["zip"] = _bulk(_rows(label) + _rows("stocks", 5) + _rows("SEP", 5))
    t = ps.fetch_tickers(tmp_path, refresh=True)
    assert len(t) == 3 and set(t["table"]) == {label}
    assert pd.api.types.is_datetime64_any_dtype(t["lastpricedate"])
    assert len(pd.read_pickle(tmp_path / "sharadar_tickers.pkl")) == 3


def test_a_download_without_enough_fundamentals_rows_raises_and_keeps_the_cache(server, tmp_path):
    server["zip"] = _bulk(_rows("SF1"))
    ps.fetch_tickers(tmp_path, refresh=True)
    server["zip"] = _bulk(_rows("stocks", 10) + _rows("renamed_again", 10))
    with pytest.raises(RuntimeError, match="only 0 fundamentals rows.*renamed_again"):
        ps.fetch_tickers(tmp_path, refresh=True)
    assert len(pd.read_pickle(tmp_path / "sharadar_tickers.pkl")) == 3       # the good master is still there


def test_an_empty_cached_master_is_downloaded_again(server, tmp_path):
    pd.DataFrame(columns=COLS).to_pickle(tmp_path / "sharadar_tickers.pkl")   # what the 2026-11-25 run left behind
    server["zip"] = _bulk(_rows("fundamentals"))
    t = ps.fetch_tickers(tmp_path)                                           # no refresh asked: still repaired
    assert len(t) == 3 and server["downloads"] == 1
    assert len(ps.fetch_tickers(tmp_path)) == 3 and server["downloads"] == 1  # a good cache is not downloaded again

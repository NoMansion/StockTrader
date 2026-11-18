"""The whole pipeline against a made-up exchange and a made-up forecaster: no network, no Claude, no money.

    python scripts/demo_offline.py

Five markets, four cycles over a pretend month. Shows what a cycle log and the status report look like, and
proves the install works before anything real is connected. Uses a throwaway database (data/demo.db).
"""
import sys

from _bootstrap import ROOT

sys.path.insert(0, str(ROOT / "tests"))

from fakes import FakeExchange, TableForecaster  # noqa: E402

from src.config import load_config  # noqa: E402
from src.ledger import Ledger  # noqa: E402
from src.trader import Trader  # noqa: E402
from src.venue import PolymarketUS  # noqa: E402

sys.path.insert(0, str(ROOT / "scripts"))
from status import report  # noqa: E402

NOW, H = 1_800_000_000.0, 3600.0


def main() -> int:
    db = ROOT / "data" / "demo.db"
    db.parent.mkdir(exist_ok=True)
    if db.exists():
        db.unlink()
    cfg = load_config()
    cfg["safety"]["kill_switch"] = "data/DEMO_STOP"
    ex = (FakeExchange(NOW)
          .add("cpi-above-3", title="Will January CPI inflation be above 3.0%?", bid=0.44, ask=0.46)
          .add("fed-holds-march", title="Will the Fed hold rates in March?", bid=0.61, ask=0.63)
          .add("gdp-above-2", title="Will Q4 GDP growth be above 2.0%?", bid=0.50, ask=0.52)
          .add("nba-finals", title="Will Boston win the NBA Finals?", category="sports")
          .add("longshot", title="Will unemployment exceed 7%?", bid=0.03, ask=0.05))
    # the pretend forecaster: likes CPI more than the market does, likes the Fed hold less, agrees on GDP
    forecaster = TableForecaster({"cpi-above-3": 0.60, "fed-holds-march": 0.45, "gdp-above-2": 0.52})
    ledger = Ledger(db)
    ledger.deposit(float(cfg["account"]["paper_bankroll"]), "deposit: demo bankroll")
    trader = Trader(cfg, ledger, PolymarketUS(ex, min_interval=0), forecaster, root=ROOT)

    def cycle(label, t):
        trader._books.clear(); trader._markets.clear()
        trader.venue.clock = lambda: t
        res = trader.run(now=t)
        print(f"\n=== {label} ===")
        print("\n".join(res.log))

    cycle("day 0: scan, forecast, place resting orders", NOW)
    ex.set_book("cpi-above-3", 0.42, 0.44)          # price dips to our bid: the resting order fills
    ex.set_book("fed-holds-march", 0.63, 0.65)      # price rises: our resting NO order fills
    cycle("day 0 + 8h: prices came to the orders", NOW + 8 * H)
    ex.set_book("cpi-above-3", 0.50, 0.52)
    ex.set_book("fed-holds-march", 0.58, 0.60)
    cycle("day 3: prices moved toward the forecasts", NOW + 73 * H)
    ex.close("cpi-above-3", settlement=1.0)
    ex.close("fed-holds-march", settlement=1.0)     # this one goes against us
    ex.close("gdp-above-2", settlement=0.0)
    cycle("day 30: markets settle", NOW + 30 * 24 * H)

    print("\n" + report(ledger, cfg))
    ledger.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Run this first on your Windows PC with Norgate Data Updater open.

    python scripts/norgate_smoke.py

Checks, in order: package import, NDU connection, one price series, delisted
database access, and index-constituent history (Platinum/Diamond). Prints a
clear pass/fail for each so you know what your subscription actually unlocks.
"""
import _bootstrap  # noqa: F401


def check(label, fn):
    try:
        out = fn()
        print(f"[ OK ] {label}: {out}")
        return out
    except Exception as e:
        print(f"[FAIL] {label}: {type(e).__name__}: {e}")
        return None


def main():
    nd = check("import norgatedata", lambda: __import__("norgatedata"))
    if nd is None:
        print("\n→ pip install norgatedata (and make sure Norgate Data Updater is running)")
        return

    check("NDU status", lambda: nd.status())
    check("databases()", lambda: nd.databases())
    n_active = check("US Equities symbol count", lambda: len(nd.database_symbols("US Equities")))
    n_delisted = check("US Equities Delisted symbol count", lambda: len(nd.database_symbols("US Equities Delisted")))

    px = check("AAPL total-return bars (last 5)", lambda: nd.price_timeseries(
        "AAPL", stock_price_adjustment_setting=nd.StockPriceAdjustmentType.TOTALRETURN,
        padding_setting=nd.PaddingType.NONE, limit=5, timeseriesformat="pandas-dataframe").shape)

    check("AAPL assetid", lambda: nd.assetid("AAPL"))
    check("AAPL GICS sector", lambda: nd.classification_at_level("AAPL", "GICS", "ClassificationName", 1))

    ic = check("index membership (S&P 500) for AAPL, rows", lambda: len(nd.index_constituent_timeseries(
        "AAPL", "S&P 500", padding_setting=nd.PaddingType.NONE, start_date="2015-01-01",
        timeseriesformat="pandas-dataframe")))

    print("\nSummary")
    print(f"  delisted database : {'yes' if n_delisted else 'NO — Platinum/Diamond needed for survivorship-free backtests'}")
    print(f"  index history     : {'yes' if ic else 'NO — Platinum/Diamond needed for universe: norgate'}")
    if n_delisted and ic:
        print("  → config.yaml can use provider: norgate, universe: norgate")
    elif n_delisted:
        print("  → use universe: liquidity instead of norgate")
    else:
        print("  → use universe: static until the subscription is upgraded")


if __name__ == "__main__":
    main()

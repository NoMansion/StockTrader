"""Daily backtest of the rank → size → rebalance loop.

Timing convention (no lookahead):
  - On day t, after the close, compute scores from bars <= t.
  - Trade at the close of day t (in practice: market-on-close orders).
  - Day t+1 P&L = sum(w_t * r_{t+1}), r = adj_close pct change.
  - Costs charged on day t from the CostModel (impact: depends on each trade's
    size vs the stock's dollar volume and your account size).

Walk-forward for ML rankers: retrain every `retrain_every_days` on a trailing
window whose labels are fully realized (train end = t - horizon).

auto_tune: at each retrain point, re-run only the *allocation* layer over the
trailing `tune_window` days using the scores already produced, for every
(risk_aversion, tc_multiplier) in the grid, and adopt the combo with the best
after-cost Sharpe. Only past data is used, so the choice is walk-forward.
"""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, field, replace
from itertools import product

import numpy as np
import pandas as pd

from .costs import CostModel, dollar_adv
from .features import compute_features, forward_excess_return, realized_vol
from .portfolio import Rules, State, drift_weights, rebalance
from .ranking import information_coefficient, make_ranker


@dataclass
class AutoTune:
    enabled: bool = False
    risk_aversion: list = field(default_factory=lambda: [4.0, 8.0, 16.0])
    tc_multiplier: list = field(default_factory=lambda: [1.0, 1.5, 2.5])
    tune_window: int = 252
    tune_rebalance_every: int = 5     # speed: weekly rebalances inside the tuning sim


@dataclass
class BacktestConfig:
    ranker: str = "momentum"
    ranker_weights: dict | None = None     # for ranker == "blend" (or to override a preset)
    horizon_days: int = 10
    retrain_every_days: int = 63
    train_window_days: int = 756
    min_train_days: int = 252
    rebalance_every_days: int = 1
    cost_model: CostModel = field(default_factory=CostModel)
    auto_tune: AutoTune = field(default_factory=AutoTune)
    warmup_days: int = 260
    sleeve: "SleeveConfig | None" = None     # idle-cash sleeve (src/sleeve.py); None = off
    cash_yield: bool = False                 # idle cash earns the T-bill yield (accounting only)
    # legacy fields kept for CLI compatibility; mapped into cost_model if set
    slippage_bps: float | None = None
    commission_per_trade: float | None = None

    def __post_init__(self):
        if self.slippage_bps is not None:
            self.cost_model = replace(self.cost_model, flat_bps=self.slippage_bps)
        if self.commission_per_trade is not None:
            self.cost_model = replace(self.cost_model, commission_per_trade=self.commission_per_trade)


@dataclass
class BacktestResult:
    daily: pd.DataFrame          # ret, bench_ret, turnover, cost, n_pos, ic, (risk_aversion, tc_multiplier if tuned)
    weights: pd.DataFrame        # date x ticker
    trades: pd.DataFrame         # long: date, ticker, delta_w
    tune_log: pd.DataFrame = field(default_factory=pd.DataFrame)

    def summary(self) -> dict:
        d = self.daily
        out = {
            **_metrics(d["ret"], "strategy"),
            **_metrics(d["bench_ret"], "benchmark"),
            "avg_daily_turnover": float(d["turnover"].mean()),
            "avg_daily_cost_bps": float(d["cost"].mean() * 1e4),
            "avg_positions": float(d["n_pos"].mean()),
            "mean_ic": float(d["ic"].mean()),
            "ic_tstat": float(d["ic"].mean() / d["ic"].std() * np.sqrt(d["ic"].notna().sum())) if d["ic"].notna().sum() > 2 else np.nan,
            "days": int(len(d)),
        }
        if not self.tune_log.empty:
            out["tuned_settings"] = self.tune_log[["date", "risk_aversion", "tc_multiplier"]].to_dict("records")
        return out


def _metrics(r: pd.Series, prefix: str) -> dict:
    r = r.dropna()
    if r.empty:
        return {}
    eq = (1 + r).cumprod()
    yrs = len(r) / 252
    cagr = eq.iloc[-1] ** (1 / yrs) - 1 if yrs > 0 else np.nan
    vol = r.std() * np.sqrt(252)
    sharpe = r.mean() / r.std() * np.sqrt(252) if r.std() > 0 else np.nan
    dd = (eq / eq.cummax() - 1).min()
    return {f"{prefix}_cagr": float(cagr), f"{prefix}_vol": float(vol), f"{prefix}_sharpe": float(sharpe), f"{prefix}_max_dd": float(dd)}


# ------------------------------------------------------------------ allocation-only simulation (for tuning)
def _simulate_allocation(score_hist: dict, rets: pd.DataFrame, adv: pd.DataFrame, vol: pd.DataFrame,
                         rules: Rules, cost_model: CostModel, dates: list, ic: float, every: int, cov_lb: int) -> float:
    """Run just the allocation layer over `dates` with precomputed scores; return Sharpe after costs."""
    state = State()
    out = []
    for k, (i, t) in enumerate(dates):
        w_prev = state.weights
        day_ret = float((w_prev * rets.loc[t].reindex(w_prev.index).fillna(0)).sum()) if not w_prev.empty else 0.0
        state.weights = drift_weights(w_prev, rets.loc[t])
        cost = 0.0
        if k % every == 0 and t in score_hist:
            ret_win = rets.iloc[max(0, i - cov_lb + 1): i + 1]
            _, trades, state = rebalance(score_hist[t], vol.loc[t], rules, state, t, returns_window=ret_win, ic=ic,
                                         adv=adv.loc[t], cost_model=cost_model)
            cost = cost_model.trade_cost(trades, adv.loc[t], rets.iloc[max(0, i - 19): i + 1].std())
        out.append(day_ret - cost)
    r = pd.Series(out)
    return float(r.mean() / r.std() * np.sqrt(252)) if r.std() > 0 else -np.inf


# ------------------------------------------------------------------ main loop
def run_backtest(
    close: pd.DataFrame,
    volume: pd.DataFrame,
    rules: Rules,
    cfg: BacktestConfig,
    membership: pd.DataFrame | None = None,
    raw_close: pd.DataFrame | None = None,
    exposure: pd.Series | None = None,
    fundamentals: dict[str, pd.DataFrame] | None = None,
) -> BacktestResult:
    """`membership` (optional): date x ticker booleans — the point-in-time
    universe. Only members on a date can be scored or bought; the benchmark
    is the equal-weight return of that day's members.
    `raw_close` (optional): unadjusted close for dollar-volume (ADV / cost
    model); defaults to `close`.
    `fundamentals` (optional): {feature: date x ticker panel} from src/fundamentals.py,
    added to the feature set (needed by the "earnings" ranker)."""
    from .universe import apply_membership

    close = close.sort_index()
    volume = volume.reindex_like(close)
    px = raw_close.reindex_like(close) if raw_close is not None else close
    if membership is not None:
        membership = membership.reindex(index=close.index, columns=close.columns).ffill().fillna(False).astype(bool)

    rets = close.pct_change()
    feats = compute_features(close, volume, raw_close=px, fundamentals=fundamentals)
    labels = forward_excess_return(close, cfg.horizon_days)
    feat_dates = set(feats.index.unique(level="date"))
    label_dates = set(labels.index.unique(level="date"))
    bench_all = (rets.where(membership) if membership is not None else rets).mean(axis=1)
    vol = realized_vol(close, 20)
    adv = dollar_adv(px, volume, 60)
    sigma20 = rets.rolling(20).std()
    ranker = make_ranker(cfg.ranker, cfg.ranker_weights) if cfg.ranker_weights else make_ranker(cfg.ranker)
    cm = cfg.cost_model

    dates = close.index
    state = State()
    rows, weight_rows, trade_rows, tune_rows = [], {}, [], []
    last_train_i = -10**9
    trained = not ranker.needs_training
    ic_hist: dict[int, float] = {}
    ic_keys: list[int] = []          # finite IC observations in day order (for the trailing mean)
    ic_vals: list[float] = []
    score_hist: dict[pd.Timestamp, pd.Series] = {}
    cov_lb = rules.optimizer.cov_lookback if rules.optimizer else 120
    tune = cfg.auto_tune
    tuned = (rules.optimizer.risk_aversion, rules.optimizer.tc_multiplier) if rules.optimizer else (np.nan, np.nan)

    def trailing_ic(i: int) -> float:
        n = bisect_right(ic_keys, i - cfg.horizon_days)
        return float(np.mean(ic_vals[max(0, n - 126):n])) if n >= 20 else np.nan

    def maybe_autotune(i: int):
        nonlocal rules, tuned
        if not (tune.enabled and rules.sizing == "optimizer" and rules.optimizer):
            return
        window = [(j, dates[j]) for j in range(max(cfg.warmup_days, i - tune.tune_window), i) if dates[j] in score_hist]
        if len(window) < 60:
            return
        ic_now = trailing_ic(i)
        best, best_s = None, -np.inf
        for ra, tcm in product(tune.risk_aversion, tune.tc_multiplier):
            trial = Rules(**{**rules.__dict__, "optimizer": replace(rules.optimizer, risk_aversion=ra, tc_multiplier=tcm)})
            s = _simulate_allocation(score_hist, rets, adv, vol, trial, cm, window, ic_now, tune.tune_rebalance_every, cov_lb)
            if s > best_s:
                best, best_s = (ra, tcm), s
        if best is not None:
            rules = Rules(**{**rules.__dict__, "optimizer": replace(rules.optimizer, risk_aversion=best[0], tc_multiplier=best[1])})
            tuned = best
            tune_rows.append({"date": dates[i], "risk_aversion": best[0], "tc_multiplier": best[1], "sharpe_in_window": best_s})

    for i, t in enumerate(dates):
        if i < cfg.warmup_days:
            continue
        # ---- walk-forward retraining (+ tuning)
        if (i - last_train_i) >= cfg.retrain_every_days:
            if ranker.needs_training:
                train_end_i = i - cfg.horizon_days
                train_start_i = max(0, train_end_i - cfg.train_window_days)
                if train_end_i - train_start_i >= cfg.min_train_days:
                    ranker.fit(feats.loc[dates[train_start_i]:dates[train_end_i]], labels, end_date=dates[train_end_i])
                    trained = True
            maybe_autotune(i)
            last_train_i = i
        if not trained:
            continue

        # ---- drift + P&L
        w_prev = state.weights
        r_t = rets.iloc[i]
        day_ret = float((w_prev * r_t.reindex(w_prev.index).fillna(0)).sum()) if not w_prev.empty else 0.0
        bench = float(bench_all.iloc[i])
        state.weights = drift_weights(w_prev, r_t)

        # ---- rebalance on schedule
        turnover, cost, ic = 0.0, 0.0, np.nan
        if (i - cfg.warmup_days) % cfg.rebalance_every_days == 0:
            f_t = feats.xs(t, level="date") if t in feat_dates else pd.DataFrame()
            if not f_t.empty:
                scores = apply_membership(ranker.score(f_t), membership, t)
                score_hist[t] = scores
                if t in label_dates:
                    ic = information_coefficient(scores, labels.xs(t, level="date"))
                    ic_hist[i] = ic
                    if np.isfinite(ic):
                        ic_keys.append(i)
                        ic_vals.append(float(ic))
                ret_win = rets.iloc[max(0, i - cov_lb + 1): i + 1] if rules.sizing == "optimizer" else None
                r_t = rules
                if exposure is not None:
                    # market-regime scaling: exposure in [0, 1] shrinks the invested budget
                    e = float(exposure.get(t, 1.0))
                    r_t = replace(rules, cash_buffer=1.0 - e * (1.0 - rules.cash_buffer))
                new_w, trades, state = rebalance(scores, vol.loc[t], r_t, state, t, returns_window=ret_win,
                                                 ic=trailing_ic(i), adv=adv.loc[t], cost_model=cm)
                turnover = float(trades.abs().sum())
                cost = cm.trade_cost(trades, adv.loc[t], sigma20.loc[t])
                for tk, dw in trades.items():
                    trade_rows.append({"date": t, "ticker": tk, "delta_w": float(dw)})

        rows.append({"date": t, "ret": day_ret - cost, "bench_ret": bench, "turnover": turnover, "cost": cost,
                     "n_pos": int((state.weights > 0).sum()), "ic": ic, "risk_aversion": tuned[0], "tc_multiplier": tuned[1]})
        weight_rows[t] = state.weights

    daily = pd.DataFrame(rows).set_index("date")
    weights = pd.DataFrame(weight_rows).T.fillna(0.0).sort_index()
    trades = pd.DataFrame(trade_rows)
    result = BacktestResult(daily=daily, weights=weights, trades=trades, tune_log=pd.DataFrame(tune_rows))
    if cfg.sleeve is not None or cfg.cash_yield:
        from .sleeve import apply_cash_yield, apply_sleeve
        if cfg.sleeve is not None:
            result = apply_sleeve(result, rules.cash_buffer, cfg.sleeve)
        if cfg.cash_yield:
            result = apply_cash_yield(result)
    return result

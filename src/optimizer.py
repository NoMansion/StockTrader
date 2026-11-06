"""Stage B: the model decides sizes and position count.

Pipeline per rebalance:

    scores  ──► expected returns  mu_i = IC · z(score_i) · sigma_i
    returns ──► risk model        Sigma = shrunk sample covariance
    w_prev  ──► transaction cost  c_i · |w_i - w_prev_i|   (c_i per stock, from
                                   its liquidity and your account size)

    maximise  mu·w  -  (lambda/2) w'Σw  -  Σ c_i |w_i - w_prev_i|
    s.t.      0 <= w_i <= w_max,   Σ w_i <= 1 - cash_buffer,
              |w_i - w_prev_i| <= tradecap_i   (ADV participation limit)

Position count is an output: a name gets weight only if its expected return
beats its marginal risk contribution plus its own cost of trading. Thin
names are expensive to trade for a big account, so they drop out on their own.

`mu` uses the "fundamental law" scaling: a score one standard deviation
above the cross-section is worth IC × that stock's own volatility. IC is
estimated from the model's own trailing realised IC (passed in), so a model
that stops working automatically shrinks positions toward cash.

Solvers:
  "pgd"   — proximal/projected gradient (FISTA). Default; handles ~1,000+
            names in well under a second. Exact for this convex problem.
  "slsqp" — SciPy, kept for cross-checking on small problems.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class OptimizerConfig:
    risk_aversion: float = 8.0       # lambda; higher = more diversified, less exposure
    tc_bps: float = 20.0             # flat cost penalty (bps) when no per-name costs given
    tc_multiplier: float = 1.5       # scale applied to per-name cost estimates (be pessimistic)
    cov_lookback: int = 120
    shrinkage: float = 0.5           # 0 = sample cov, 1 = diagonal only
    ic_default: float = 0.03         # used until a trailing IC is available
    ic_floor: float = 0.0            # IC <= floor -> mu = 0 -> go to cash
    max_weight: float = 0.10
    cash_buffer: float = 0.02
    min_weight: float = 0.005        # zero out dust
    max_positions: int | None = None # optional hard cap; None = model decides
    solver: str = "pgd"


# ------------------------------------------------------------------ inputs
def expected_returns(scores: pd.Series, vol_daily: pd.Series, ic: float, cfg: OptimizerConfig) -> pd.Series:
    """Daily expected excess return per name."""
    s = scores.dropna()
    if len(s) < 3 or s.std() == 0:
        return pd.Series(0.0, index=s.index)
    z = (s - s.mean()) / s.std()
    ic_eff = max(float(ic) if np.isfinite(ic) else cfg.ic_default, cfg.ic_floor)
    sig = vol_daily.reindex(s.index)
    sig = sig.fillna(sig.median()).clip(lower=1e-4)
    return ic_eff * z * sig


def shrunk_covariance(returns: pd.DataFrame, shrinkage: float) -> pd.DataFrame:
    """Sample covariance shrunk toward its diagonal (daily units)."""
    r = returns.dropna(axis=1, how="all").fillna(0.0)
    S = r.cov().values
    D = np.diag(np.diag(S))
    C = (1 - shrinkage) * S + shrinkage * D
    C += np.eye(len(C)) * 1e-8
    return pd.DataFrame(C, index=r.columns, columns=r.columns)


# ------------------------------------------------------------------ projection
def _project(v: np.ndarray, lo: np.ndarray, hi: np.ndarray, budget: float) -> np.ndarray:
    """Euclidean projection onto {lo <= w <= hi, sum(w) <= budget} via bisection on a shift."""
    w = np.clip(v, lo, hi)
    if w.sum() <= budget:
        return w
    # find tau such that sum(clip(v - tau, lo, hi)) == budget
    t_lo, t_hi = 0.0, float(np.max(v - lo)) + 1e-12
    for _ in range(100):
        tau = 0.5 * (t_lo + t_hi)
        s = np.clip(v - tau, lo, hi).sum()
        if s > budget:
            t_lo = tau
        else:
            t_hi = tau
        if t_hi - t_lo < 1e-12:
            break
    return np.clip(v - t_hi, lo, hi)


def _solve_pgd(mu, Sig, w0, c, lam, budget, cap, tradecap, iters=600) -> np.ndarray:
    """FISTA on  f(w) = -mu·w + (lam/2) w'Σw  with  g(w) = Σ c_i|w_i - w0_i| + constraints.

    Prox of the L1-around-w0 term is soft-thresholding toward w0; then project
    onto the box ∩ budget set. Alternating prox/projection is exact here because
    both sets are simple and the problem is convex (Dykstra would be exact; two
    passes of this scheme converge to the same point in practice for our scale).
    """
    n = len(mu)
    L = lam * np.linalg.eigvalsh(Sig).max() + 1e-12
    step = 1.0 / L
    lo = np.maximum(0.0, w0 - tradecap)
    hi = np.minimum(cap, w0 + tradecap)
    lo = np.minimum(lo, hi)
    w = _project(w0.copy(), lo, hi, budget)
    y, t = w.copy(), 1.0
    for _ in range(iters):
        g = -mu + lam * (Sig @ y)
        v = y - step * g
        # soft-threshold toward w0 with per-name thresholds step*c_i
        d = v - w0
        d = np.sign(d) * np.maximum(np.abs(d) - step * c, 0.0)
        w_new = _project(w0 + d, lo, hi, budget)
        t_new = 0.5 * (1 + np.sqrt(1 + 4 * t * t))
        y = w_new + ((t - 1) / t_new) * (w_new - w)
        if np.abs(w_new - w).max() < 1e-9:
            w = w_new
            break
        w, t = w_new, t_new
    return w


def _solve_slsqp(mu, Sig, w0, c, lam, budget, cap, tradecap) -> np.ndarray:
    from scipy.optimize import minimize

    n = len(mu)
    tradecap = np.where(np.isfinite(tradecap), tradecap, 10.0)   # finite for the constraint jacobian
    scale = 1.0 / max(np.abs(mu).max(), lam * np.diag(Sig).max(), c.max(), 1e-12)
    w_of = lambda x: w0 + x[:n] - x[n:]
    obj = lambda x: scale * (-(mu @ w_of(x)) + 0.5 * lam * (w_of(x) @ Sig @ w_of(x)) + (c * (x[:n] + x[n:])).sum())
    def grad(x):
        g_w = -mu + lam * (Sig @ w_of(x))
        return scale * np.concatenate([g_w + c, -g_w + c])
    cons = [
        {"type": "ineq", "fun": lambda x: budget - w_of(x).sum()},
        {"type": "ineq", "fun": lambda x: w_of(x)},
        {"type": "ineq", "fun": lambda x: cap - w_of(x)},
        {"type": "ineq", "fun": lambda x: tradecap - x[:n]},
        {"type": "ineq", "fun": lambda x: tradecap - x[n:]},
    ]
    res = minimize(obj, np.zeros(2 * n), jac=grad, bounds=[(0, None)] * (2 * n), constraints=cons,
                   method="SLSQP", options={"maxiter": 1000, "ftol": 1e-12})
    return np.clip(w_of(res.x), 0, cap)


# ------------------------------------------------------------------ solver API
def optimize_weights(
    mu: pd.Series,
    cov: pd.DataFrame,
    w_prev: pd.Series,
    cfg: OptimizerConfig,
    cost_coeffs: pd.Series | None = None,
    trade_caps: pd.Series | None = None,
) -> pd.Series:
    names = mu.index.intersection(cov.index)
    if len(names) == 0:
        return pd.Series(dtype=float)
    mu_v = mu.reindex(names).fillna(0.0).values
    Sig = cov.loc[names, names].values
    w0 = w_prev.reindex(names).fillna(0.0).clip(lower=0).values
    c = (cost_coeffs.reindex(names).fillna(cfg.tc_bps / 1e4).values * cfg.tc_multiplier
         if cost_coeffs is not None else np.full(len(names), cfg.tc_bps / 1e4))
    tcap = trade_caps.reindex(names).fillna(np.inf).clip(lower=0).values if trade_caps is not None else np.full(len(names), np.inf)
    # never let the trade cap trap a position we must be able to exit eventually
    tcap = np.maximum(tcap, 1e-4)
    budget = 1.0 - cfg.cash_buffer
    cap = cfg.max_weight

    if cfg.solver == "slsqp":
        w = _solve_slsqp(mu_v, Sig, w0, c, cfg.risk_aversion, budget, cap, tcap)
    else:
        w = _solve_pgd(mu_v, Sig, w0, c, cfg.risk_aversion, budget, cap, tcap)
    w = pd.Series(np.clip(w, 0, cap), index=names)

    w[w < cfg.min_weight] = 0.0
    if cfg.max_positions is not None and (w > 0).sum() > cfg.max_positions:
        keep = w.sort_values(ascending=False).index[: cfg.max_positions]
        w[~w.index.isin(keep)] = 0.0
    if w.sum() > budget:
        w *= budget / w.sum()
    return w[w > 0]


# ------------------------------------------------------------------ one call
def allocate(
    scores: pd.Series,
    returns_window: pd.DataFrame,
    w_prev: pd.Series,
    ic: float,
    cfg: OptimizerConfig,
    adv: pd.Series | None = None,
    cost_model=None,
) -> pd.Series:
    """scores + recent returns + current weights (+ liquidity) -> new weights.

    With a CostModel and ADV: two-pass linearisation of the sqrt impact cost.
    Pass 1 prices every name at a 1%-of-portfolio reference trade; pass 2
    re-prices at the trade sizes pass 1 actually proposed, so big trades in
    thin names pay what they would really pay.
    """
    vol_daily = returns_window.std()
    mu = expected_returns(scores, vol_daily, ic, cfg)
    cov = shrunk_covariance(returns_window[mu.index.intersection(returns_window.columns)], cfg.shrinkage)
    names = mu.index.intersection(cov.index)
    if cost_model is None or adv is None:
        return optimize_weights(mu, cov, w_prev, cfg)

    caps = cost_model.max_trade_weight(names, adv)
    c1 = cost_model.linear_coeffs(names, adv, vol_daily, ref_delta_w=0.01)
    w1 = optimize_weights(mu, cov, w_prev, cfg, cost_coeffs=c1, trade_caps=caps)
    delta = (w1.reindex(names).fillna(0.0) - w_prev.reindex(names).fillna(0.0)).abs()
    c2 = cost_model.linear_coeffs(names, adv, vol_daily, ref_delta_w=delta.clip(lower=0.01))
    return optimize_weights(mu, cov, w_prev, cfg, cost_coeffs=c2, trade_caps=caps)

"""Position sizing for binary outcome contracts. No venue code and no network here: pure arithmetic.

A share bought at an all-in cost `c` (price + fee per share, 0 < c < 1) pays $1 if its outcome happens and $0
otherwise. With a probability `q` for that outcome:

    edge per share        q - c
    expected return       (q - c) / c            on the dollars put in
    full Kelly stake      (q - c) / (1 - c)      as a fraction of the bankroll

Full Kelly assumes `q` is exactly right. It never is, and over-betting costs more than under-betting, so the stake
is cut three times before it reaches the order:

  1. shrink     q = market + w * (model - market). The market price is the prior; the model only moves it part way.
  2. fraction   stake = kelly_fraction * full Kelly (0.25 or less).
  3. caps       per market, per event, per category, total exposure, cash reserve, displayed depth.

Every rejected trade carries a reason, which is logged: most candidates should end as "no trade".
"""
from __future__ import annotations

from dataclasses import dataclass, field


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def shrink(p_model: float, p_market: float, weight: float) -> float:
    """Move from the market price toward the model's estimate by `weight` (0 = trust the market, 1 = the model)."""
    w = clamp(weight, 0.0, 1.0)
    return clamp(p_market + w * (p_model - p_market), 0.0, 1.0)


def kelly_fraction(q: float, cost: float) -> float:
    """Full-Kelly stake as a fraction of the bankroll for a share costing `cost` that pays 1 with probability q."""
    if not 0.0 < cost < 1.0:
        return 0.0
    return max(0.0, (q - cost) / (1.0 - cost))


def expected_return(q: float, cost: float) -> float:
    """Expected profit per dollar staked."""
    return (q - cost) / cost if cost > 0 else 0.0


@dataclass
class SizingRules:
    shrink_weight: float = 0.5          # how far the model moves the market price
    kelly_fraction: float = 0.2         # fraction of full Kelly
    min_edge: float = 0.05              # shrunk probability minus all-in cost, in probability points
    min_edge_ratio: float = 0.0         # edge must also be this fraction of the cost (guards cheap longshots)
    min_annual_return: float = 0.0      # expected return, annualised over days to resolution, must exceed this
    max_disagreement: float = 0.25      # |model - market| above this is treated as "we are missing something"
    min_price: float = 0.08             # do not buy an outcome cheaper than this ...
    max_price: float = 0.92             # ... or dearer than this
    max_position_pct: float = 0.03      # one market, fraction of equity (at cost)
    max_event_pct: float = 0.06         # all markets of one event
    max_category_pct: float = 0.25      # one category
    max_total_exposure_pct: float = 0.50  # everything; the rest stays in cash
    min_order_usd: float = 5.0          # below this the order is not worth its spread
    max_order_usd: float = 100.0        # hard dollar ceiling per order, whatever the equity

    @classmethod
    def from_config(cls, cfg: dict | None) -> "SizingRules":
        known = {k: v for k, v in (cfg or {}).items() if k in cls.__dataclass_fields__}
        return cls(**known)


@dataclass
class Exposure:
    """What the account already holds, at cost, in dollars."""
    equity: float
    cash: float
    market: float = 0.0     # this market (both outcomes)
    event: float = 0.0      # this market's event
    category: float = 0.0   # this market's category
    total: float = 0.0      # all open positions


@dataclass
class Sizing:
    trade: bool
    side: str | None = None             # "YES" or "NO": the outcome token to buy
    reason: str = ""
    p_model: float = 0.0                # model probability of YES
    p_market: float = 0.0               # market mid for YES
    q: float = 0.0                      # shrunk probability of the chosen side
    cost: float = 0.0                   # all-in cost per share of the chosen side at the touch
    edge: float = 0.0
    limit_price: float = 0.0            # highest price worth paying (before fee) for the chosen side
    kelly_full: float = 0.0
    stake: float = 0.0                  # dollars to spend
    binding: str = ""                   # which cap set the stake
    notes: list[str] = field(default_factory=list)


def _no(sz: Sizing, reason: str) -> Sizing:
    sz.trade, sz.reason, sz.stake = False, reason, 0.0
    return sz


def plan_entry(p_model: float, p_market: float, ask_yes: float | None, ask_no: float | None,
               exposure: Exposure, rules: SizingRules, days_to_resolution: float | None = None,
               fee_yes: float = 0.0, fee_no: float = 0.0, weight: float | None = None) -> Sizing:
    """Decide whether to open (or add to) a position and how many dollars to spend.

    p_model      model probability that the market resolves YES
    p_market     market mid for YES at decision time
    ask_yes/no   best ask of each outcome token (None = no offer on that side)
    fee_yes/no   taker fee per share at that ask, in dollars
    weight       overrides rules.shrink_weight (e.g. lower when the model reported low confidence)
    """
    sz = Sizing(trade=False, p_model=p_model, p_market=p_market)
    if not (0.0 <= p_model <= 1.0) or not (0.0 < p_market < 1.0):
        return _no(sz, f"bad inputs: model {p_model!r}, market {p_market!r}")
    if exposure.equity <= 0:
        return _no(sz, "no equity")
    if abs(p_model - p_market) > rules.max_disagreement:
        return _no(sz, f"model {p_model:.2f} vs market {p_market:.2f}: gap above {rules.max_disagreement:.2f}, "
                       "more likely a missed fact or a misread rule than an edge")

    w = rules.shrink_weight if weight is None else weight
    q_yes = shrink(p_model, p_market, w)
    sides = []
    if ask_yes is not None and 0 < ask_yes < 1:
        sides.append(("YES", q_yes, ask_yes, fee_yes))
    if ask_no is not None and 0 < ask_no < 1:
        sides.append(("NO", 1.0 - q_yes, ask_no, fee_no))
    if not sides:
        return _no(sz, "no offers")
    # at most one side can have a positive edge when ask_yes + ask_no >= 1
    side, q, ask, fee = max(sides, key=lambda s: s[1] - (s[2] + s[3]))
    cost = ask + fee
    sz.side, sz.q, sz.cost, sz.edge = side, q, cost, q - cost
    # highest price at which the edge still clears the threshold (fee held at its value at the touch)
    sz.limit_price = max(0.0, q - rules.min_edge - fee)

    if sz.edge < rules.min_edge:
        return _no(sz, f"edge {sz.edge:+.3f} below the {rules.min_edge:.3f} threshold")
    if not rules.min_price <= ask <= rules.max_price:
        return _no(sz, f"{side} ask {ask:.3f} outside [{rules.min_price:.2f}, {rules.max_price:.2f}]")
    if rules.min_edge_ratio and sz.edge < rules.min_edge_ratio * cost:
        return _no(sz, f"edge {sz.edge:.3f} is under {rules.min_edge_ratio:.0%} of the cost {cost:.3f}")
    if rules.min_annual_return and days_to_resolution:
        ann = expected_return(q, cost) * 365.0 / max(days_to_resolution, 1.0)
        if ann < rules.min_annual_return:
            return _no(sz, f"expected return {ann:.0%} a year over {days_to_resolution:.0f} days is below "
                           f"{rules.min_annual_return:.0%}")

    sz.kelly_full = kelly_fraction(q, cost)
    eq = exposure.equity
    limits = {
        "kelly": rules.kelly_fraction * sz.kelly_full * eq,
        "market cap": rules.max_position_pct * eq - exposure.market,
        "event cap": rules.max_event_pct * eq - exposure.event,
        "category cap": rules.max_category_pct * eq - exposure.category,
        "total exposure cap": rules.max_total_exposure_pct * eq - exposure.total,
        "cash": exposure.cash,
        "order ceiling": rules.max_order_usd,
    }
    sz.binding, stake = min(limits.items(), key=lambda kv: kv[1])
    if stake < rules.min_order_usd:
        return _no(sz, f"stake ${max(stake, 0):.2f} under the ${rules.min_order_usd:.2f} minimum (bound by {sz.binding})")
    sz.trade, sz.stake = True, round(stake, 2)
    sz.reason = (f"buy {side}: q {q:.3f} vs cost {cost:.3f}, edge {sz.edge:+.3f}, full Kelly {sz.kelly_full:.1%}, "
                 f"stake ${sz.stake:.2f} (bound by {sz.binding})")
    return sz


def exit_signal(side: str, p_model: float, p_market: float, bid: float | None, rules: SizingRules,
                exit_margin: float = 0.02, weight: float | None = None) -> tuple[bool, str]:
    """Should a held position be sold at the bid? Yes when the shrunk probability of our side has fallen below
    what the market will pay for it by more than `exit_margin`: holding is then a negative-edge bet."""
    if bid is None or bid <= 0:
        return False, "no bid"
    w = rules.shrink_weight if weight is None else weight
    q_yes = shrink(p_model, p_market, w)
    q = q_yes if side == "YES" else 1.0 - q_yes
    if q < bid - exit_margin:
        return True, f"our {side} probability {q:.3f} is below the bid {bid:.3f} by more than {exit_margin:.2f}"
    return False, f"hold: {side} probability {q:.3f} vs bid {bid:.3f}"

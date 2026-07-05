"""A real, documented momentum strategy with risk management.

Signal (dual moving-average crossover + trend filter):
  - Fast SMA (default 20d) crossing ABOVE slow SMA (default 50d) = uptrend -> long
  - Fast crossing BELOW slow = exit
  - A long-term filter (200d SMA) blocks longs when price is below it (avoid
    buying into bear markets — the single biggest killer of naive crossover systems).

Risk management (this is what separates a strategy from a gamble):
  - Position sizing: risk a fixed % of equity per trade (default 1%), sized off
    the stop distance so every trade risks the same dollar amount.
  - Hard stop-loss: exit if price falls a set % below entry (default 8%).

None of this is a promise of profit. It is a disciplined, testable rule set.
Validate it with backtest.py before trusting it with money.
"""
from dataclasses import dataclass


@dataclass
class Params:
    fast: int = 20
    slow: int = 50
    trend: int = 200
    risk_per_trade: float = 0.01   # 1% of equity risked per position
    stop_pct: float = 0.08         # exit 8% below entry


def sma(values, n):
    if len(values) < n:
        return None
    return sum(values[-n:]) / n


def signal(closes, params: Params):
    """Return 'buy' | 'sell' | 'hold' from a list of closing prices (oldest->newest)."""
    if len(closes) < params.slow + 2:
        return "hold"
    fast_now = sma(closes, params.fast)
    slow_now = sma(closes, params.slow)
    fast_prev = sma(closes[:-1], params.fast)
    slow_prev = sma(closes[:-1], params.slow)
    trend_now = sma(closes, params.trend) if len(closes) >= params.trend else 0
    price = closes[-1]

    crossed_up = fast_prev <= slow_prev and fast_now > slow_now
    crossed_down = fast_prev >= slow_prev and fast_now < slow_now

    if crossed_up and price > (trend_now or 0):
        return "buy"
    if crossed_down:
        return "sell"
    return "hold"


def position_size(equity, price, params: Params):
    """Shares to buy so that hitting the stop loses ~risk_per_trade of equity."""
    dollars_at_risk = equity * params.risk_per_trade
    per_share_risk = price * params.stop_pct
    if per_share_risk <= 0:
        return 0
    return max(0, int(dollars_at_risk / per_share_risk))

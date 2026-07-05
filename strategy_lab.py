"""Strategy lab: test SEVERAL real strategies head-to-head on the same data,
so we learn from evidence which approaches hold up and which don't.

Strategies compared (all on SPY, 2018-2025, same $100k start):
  1. Buy & Hold            - the baseline everything must beat
  2. SMA Crossover         - classic trend timing (20/50)
  3. RSI Mean-Reversion    - buy oversold dips, sell overbought
  4. Dual-Momentum / 200d  - hold only while above the 200-day average
  5. Monthly DCA           - drip a fixed sum in every month, never sell

Reports: total return, max drawdown, and a crude risk-adjusted score
(return per unit of drawdown). Learning > profit here.

Run: python strategy_lab.py
"""
import sys
from datetime import datetime

import config
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

START, END, CASH = datetime(2018, 1, 1), datetime(2025, 1, 1), 100_000


def sma(v, n):
    return sum(v[-n:]) / n if len(v) >= n else None


def rsi(v, n=14):
    if len(v) < n + 1:
        return 50
    gains = losses = 0.0
    for i in range(-n, 0):
        ch = v[i] - v[i - 1]
        gains += max(ch, 0); losses += max(-ch, 0)
    if losses == 0:
        return 100
    rs = (gains / n) / (losses / n)
    return 100 - 100 / (1 + rs)


def max_drawdown(curve):
    peak, dd = -1e9, 0
    for e in curve:
        peak = max(peak, e)
        dd = min(dd, (e / peak - 1) * 100)
    return dd


def run(closes, decide, allow_partial=False):
    """Generic engine. `decide(window, holding)` -> 'buy'|'sell'|'hold'."""
    cash, shares, curve = CASH, 0, []
    for i in range(60, len(closes)):
        w = closes[:i + 1]; price = w[-1]
        curve.append(cash + shares * price)
        d = decide(w, shares > 0)
        if d == "buy" and cash >= price:
            q = int(cash / price); shares += q; cash -= q * price
        elif d == "sell" and shares > 0:
            cash += shares * price; shares = 0
    cash += shares * closes[-1]
    return (cash / CASH - 1) * 100, max_drawdown(curve)


def strat_buyhold(closes):
    shares = CASH / closes[60]
    curve = [shares * c for c in closes[60:]]
    return (curve[-1] / CASH - 1) * 100, max_drawdown(curve)


def strat_sma(w, holding):
    f, s = sma(w, 20), sma(w, 50)
    fp, sp = sma(w[:-1], 20), sma(w[:-1], 50)
    if None in (f, s, fp, sp): return "hold"
    if fp <= sp and f > s: return "buy"
    if fp >= sp and f < s: return "sell"
    return "hold"


def strat_rsi(w, holding):
    r = rsi(w)
    if r < 30 and not holding: return "buy"
    if r > 70 and holding: return "sell"
    return "hold"


def strat_200d(w, holding):
    m = sma(w, 200)
    if m is None: return "hold"
    if w[-1] > m and not holding: return "buy"
    if w[-1] < m and holding: return "sell"
    return "hold"


def strat_dca(closes):
    # invest a fixed slice every ~21 trading days, never sell
    slice_cash = CASH
    per = slice_cash / (len(closes) // 21 + 1)
    cash, shares, curve = slice_cash, 0, []
    for i in range(len(closes)):
        if i % 21 == 0 and cash >= per:
            q = per / closes[i]; shares += q; cash -= per
        curve.append(cash + shares * closes[i])
    return (curve[-1] / CASH - 1) * 100, max_drawdown(curve)


def main():
    if not config.ALPACA_API_KEY:
        print("Need Alpaca keys in .env."); sys.exit(1)
    c = StockHistoricalDataClient(config.ALPACA_API_KEY, config.ALPACA_SECRET_KEY)
    bars = c.get_stock_bars(StockBarsRequest(
        symbol_or_symbols="SPY", timeframe=TimeFrame.Day, start=START, end=END
    )).data["SPY"]
    closes = [b.close for b in bars]

    rows = []
    r, dd = strat_buyhold(closes);           rows.append(("Buy & Hold", r, dd))
    r, dd = run(closes, strat_sma);          rows.append(("SMA Crossover 20/50", r, dd))
    r, dd = run(closes, strat_rsi);          rows.append(("RSI Mean-Reversion", r, dd))
    r, dd = run(closes, strat_200d);         rows.append(("200-day Trend", r, dd))
    r, dd = strat_dca(closes);               rows.append(("Monthly DCA", r, dd))

    print(f"\nSPY 2018-2025  |  5 strategies, same $100k\n")
    print(f"{'STRATEGY':<22}{'RETURN %':>10}{'MAX DD %':>10}{'RET/DD':>9}")
    print("-" * 51)
    for name, ret, dd in rows:
        score = ret / abs(dd) if dd else 0
        print(f"{name:<22}{ret:>10.1f}{dd:>10.1f}{score:>9.2f}")
    print("-" * 51)
    print("RET/DD = return per unit of pain. Higher = better risk-adjusted.")
    print("Watch which 'clever' strategies still lose to Buy & Hold and DCA.")


if __name__ == "__main__":
    main()

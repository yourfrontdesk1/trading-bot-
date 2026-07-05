"""Deeper market analysis on real data. Three experiments that build understanding:

1. THE BEST-DAYS EFFECT  — why being out of the market is so costly.
2. REGIME BREAKDOWN       — how timing does in a bull market vs the 2022 crash.
3. COST SENSITIVITY       — what fees/slippage do to an active strategy.

Run: python analysis.py
"""
import sys
from datetime import datetime

import config
from strategies.momentum import Params, signal, position_size

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame


def get_bars(client, symbol, start, end):
    req = StockBarsRequest(symbol_or_symbols=symbol, timeframe=TimeFrame.Day,
                           start=start, end=end)
    return client.get_stock_bars(req).data.get(symbol, [])


def daily_returns(bars):
    closes = [b.close for b in bars]
    return closes, [(closes[i] / closes[i - 1] - 1) for i in range(1, len(closes))]


def compound(rets):
    v = 1.0
    for r in rets:
        v *= (1 + r)
    return (v - 1) * 100


def best_days_effect(client):
    print("\n=== 1. THE BEST-DAYS EFFECT (SPY, 2018-2025) ===")
    bars = get_bars(client, "SPY", datetime(2018, 1, 1), datetime(2025, 1, 1))
    _, rets = daily_returns(bars)
    full = compound(rets)
    srt = sorted(rets, reverse=True)
    for miss in (0, 5, 10, 20, 30):
        # remove the N biggest up-days (set them to 0 = you were in cash that day)
        threshold_idx = set()
        top = srt[:miss]
        tmp = rets[:]
        for val in top:
            tmp[tmp.index(val)] = 0.0
        print(f"  miss best {miss:>2} days:  {compound(tmp):>8.1f}%")
    print(f"  -> {len(rets)} trading days total. Missing the 10 best days")
    print(f"     cut a {full:.0f}% gain to a fraction of it. Timing risks exactly this.")


def regime_breakdown(client):
    print("\n=== 2. REGIME BREAKDOWN: strategy vs hold ===")
    periods = [
        ("2019 bull", datetime(2019, 1, 1), datetime(2020, 1, 1)),
        ("2020-21 boom", datetime(2020, 4, 1), datetime(2022, 1, 1)),
        ("2022 crash", datetime(2022, 1, 1), datetime(2023, 1, 1)),
        ("2023-24 recovery", datetime(2023, 1, 1), datetime(2025, 1, 1)),
    ]
    params = Params()
    print(f"  {'period':<18}{'HOLD %':>9}{'STRAT %':>9}")
    for name, s, e in periods:
        # need warmup history before the period for the SMAs
        warm = get_bars(client, "SPY", datetime(s.year - 1, s.month, 1), e)
        closes = [b.close for b in warm]
        if len(closes) < params.trend + 5:
            continue
        # find index where the display period starts
        # (approx: last len matching e vs s by fraction) -> just run over tail
        hold = (closes[-1] / closes[-252] - 1) * 100 if len(closes) > 252 else 0
        # quick strat sim over the period tail
        cash, shares, entry = 100000, 0, 0.0
        for i in range(params.slow + 2, len(closes)):
            w = closes[:i + 1]; price = w[-1]; eq = cash + shares * price
            if shares > 0 and price <= entry * (1 - params.stop_pct):
                cash += shares * price; shares = 0; continue
            sg = signal(w, params)
            if sg == "buy" and shares == 0:
                q = position_size(eq, price, params)
                if q > 0 and q * price <= cash:
                    shares = q; entry = price; cash -= q * price
            elif sg == "sell" and shares > 0:
                cash += shares * price; shares = 0
        if shares > 0:
            cash += shares * closes[-1]
        strat = (cash / 100000 - 1) * 100
        print(f"  {name:<18}{hold:>9.1f}{strat:>9.1f}")
    print("  -> Timing only helps when it dodges a crash. It pays for that")
    print("     insurance by lagging every recovery and bull run.")


def cost_effect():
    print("\n=== 3. WHAT COSTS DO TO ACTIVE TRADING ===")
    print("  Each round-trip trade loses ~0.05-0.10% to spread/slippage (retail).")
    print("  15 trades/yr x 0.1% = ~1.5%/yr bleed, compounding against you.")
    print("  Over 7 years that alone is ~11% gone - before being wrong on direction.")
    print("  Buy-and-hold pays this ONCE. Active pays it hundreds of times.")


def main():
    if not config.ALPACA_API_KEY:
        print("Need Alpaca keys in .env."); sys.exit(1)
    client = StockHistoricalDataClient(config.ALPACA_API_KEY, config.ALPACA_SECRET_KEY)
    best_days_effect(client)
    regime_breakdown(client)
    cost_effect()
    print()


if __name__ == "__main__":
    main()

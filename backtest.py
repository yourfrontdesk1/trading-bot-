"""Backtest the momentum strategy on real historical Alpaca data.

This exists to CONTRADICT optimism with evidence. It replays the exact rules in
strategies/momentum.py bar-by-bar (no peeking at the future) and reports the
numbers that matter: total return vs just buying and holding, max drawdown,
win rate, and number of trades.

Run:  python backtest.py
"""
import sys
from datetime import datetime

import config
from strategies.momentum import Params, signal, position_size

try:
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame
except ImportError:
    print("alpaca-py not installed. Run: pip install -r requirements.txt")
    sys.exit(1)

SYMBOLS = ["AAPL", "MSFT", "SPY", "NVDA", "AMD", "TSM"]
START = datetime(2018, 1, 1)
END = datetime(2025, 1, 1)
STARTING_CASH = 100_000


def load_closes(client, symbol):
    req = StockBarsRequest(
        symbol_or_symbols=symbol, timeframe=TimeFrame.Day, start=START, end=END
    )
    bars = client.get_stock_bars(req).data.get(symbol, [])
    return [b.close for b in bars]


def backtest_symbol(closes, params):
    """Replay the strategy on one symbol. Returns dict of results."""
    cash = STARTING_CASH
    shares = 0
    entry = 0.0
    trades = []  # (pnl_pct,)
    equity_curve = []

    for i in range(params.slow + 2, len(closes)):
        window = closes[:i + 1]
        price = window[-1]
        equity = cash + shares * price
        equity_curve.append(equity)

        # stop-loss check first
        if shares > 0 and price <= entry * (1 - params.stop_pct):
            cash += shares * price
            trades.append((price / entry - 1) * 100)
            shares = 0
            continue

        sig = signal(window, params)
        if sig == "buy" and shares == 0:
            qty = position_size(equity, price, params)
            cost = qty * price
            if qty > 0 and cost <= cash:
                shares = qty
                entry = price
                cash -= cost
        elif sig == "sell" and shares > 0:
            cash += shares * price
            trades.append((price / entry - 1) * 100)
            shares = 0

    # close any open position at the end
    if shares > 0:
        cash += shares * closes[-1]
        trades.append((closes[-1] / entry - 1) * 100)

    final = cash
    strat_return = (final / STARTING_CASH - 1) * 100
    buyhold_return = (closes[-1] / closes[params.slow + 2] - 1) * 100

    # max drawdown of the equity curve
    peak = -1e9
    max_dd = 0
    for e in equity_curve:
        peak = max(peak, e)
        max_dd = min(max_dd, (e / peak - 1) * 100)

    wins = [t for t in trades if t > 0]
    win_rate = (len(wins) / len(trades) * 100) if trades else 0
    return {
        "strat": strat_return,
        "buyhold": buyhold_return,
        "max_dd": max_dd,
        "trades": len(trades),
        "win_rate": win_rate,
    }


def main():
    if not config.ALPACA_API_KEY:
        print("Need Alpaca keys in .env to pull historical data.")
        sys.exit(1)
    client = StockHistoricalDataClient(config.ALPACA_API_KEY, config.ALPACA_SECRET_KEY)
    params = Params()

    print(f"\nBacktest {START:%Y}-{END:%Y}  |  strategy vs buy-and-hold\n")
    print(f"{'SYM':<6}{'STRAT %':>10}{'HOLD %':>10}{'MAXDD %':>10}{'TRADES':>8}{'WIN %':>8}")
    print("-" * 52)
    agg = {"strat": [], "buyhold": []}
    for sym in SYMBOLS:
        try:
            closes = load_closes(client, sym)
            if len(closes) < params.trend:
                print(f"{sym:<6}  not enough data")
                continue
            r = backtest_symbol(closes, params)
            agg["strat"].append(r["strat"])
            agg["buyhold"].append(r["buyhold"])
            print(f"{sym:<6}{r['strat']:>10.1f}{r['buyhold']:>10.1f}"
                  f"{r['max_dd']:>10.1f}{r['trades']:>8}{r['win_rate']:>8.0f}")
        except Exception as e:
            print(f"{sym:<6}  error: {e}")

    if agg["strat"]:
        print("-" * 52)
        n = len(agg["strat"])
        print(f"{'AVG':<6}{sum(agg['strat'])/n:>10.1f}{sum(agg['buyhold'])/n:>10.1f}")
        print("\nIf STRAT avg < HOLD avg, the strategy LOST to doing nothing.")


if __name__ == "__main__":
    main()

"""Main loop: check stocks via Alpaca, scan prediction markets via Polymarket.

Safe by default:
  - ALPACA_PAPER=true  -> fake money on Alpaca
  - DRY_RUN=true       -> logs intended trades, places nothing
"""
import time
import logging

import config
from brokers.polymarket_client import PolymarketClient
from strategies import example

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("bot")

WATCHLIST = ["AAPL", "MSFT", "SPY"]  # stocks to trade; edit freely


def run_stocks():
    """Trade the stock watchlist through Alpaca. Skips cleanly if keys are missing."""
    try:
        from brokers.alpaca_client import AlpacaClient
        alp = AlpacaClient()
    except Exception as e:
        log.info("[stocks] skipped: %s", e)
        return

    mode = "PAPER" if config.ALPACA_PAPER else "LIVE"
    log.info("[stocks] %s account equity: $%.2f", mode, alp.account_value())

    for symbol in WATCHLIST:
        try:
            price = alp.latest_price(symbol)
            held = alp.position_qty(symbol)
            action, qty = example.stock_decision(symbol, price, held)
            if action == "hold":
                log.info("[stocks] %s $%.2f  hold (%.0f held)", symbol, price, held)
                continue
            if config.DRY_RUN:
                log.info("[stocks] DRY_RUN would %s %s x%s @ $%.2f", action, symbol, qty, price)
                continue
            (alp.buy if action == "buy" else alp.sell)(symbol, qty)
            log.info("[stocks] %s %s x%s @ $%.2f  SUBMITTED", action.upper(), symbol, qty, price)
        except Exception as e:
            log.info("[stocks] %s error: %s", symbol, e)


def run_predictions():
    """Scan Polymarket for mispriced outcomes. Read-only for now."""
    try:
        poly = PolymarketClient()
        markets = poly.active_markets(limit=25)
    except Exception as e:
        log.info("[predict] skipped: %s", e)
        return

    notes = example.prediction_scan(markets, PolymarketClient.outcome_prices)
    if not notes:
        log.info("[predict] scanned %d markets, nothing flagged", len(markets))
    for n in notes:
        log.info("[predict] long-shot: %s", n)


def main():
    log.info("bot starting  (DRY_RUN=%s, poll=%ss)", config.DRY_RUN, config.POLL_SECONDS)
    while True:
        run_stocks()
        run_predictions()
        log.info("sleeping %ss ...", config.POLL_SECONDS)
        time.sleep(config.POLL_SECONDS)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("stopped by user")

"""Thin wrapper around Alpaca for stock trading. Defaults to paper (fake money)."""
import config

try:
    from alpaca.trading.client import TradingClient
    from alpaca.trading.requests import MarketOrderRequest
    from alpaca.trading.enums import OrderSide, TimeInForce
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockLatestQuoteRequest
    _SDK = True
except ImportError:
    _SDK = False


class AlpacaClient:
    def __init__(self):
        if not _SDK:
            raise RuntimeError("alpaca-py not installed. Run: pip install -r requirements.txt")
        if not config.ALPACA_API_KEY or not config.ALPACA_SECRET_KEY:
            raise RuntimeError("Missing ALPACA_API_KEY / ALPACA_SECRET_KEY in .env")
        self.trading = TradingClient(
            config.ALPACA_API_KEY, config.ALPACA_SECRET_KEY, paper=config.ALPACA_PAPER
        )
        self.data = StockHistoricalDataClient(
            config.ALPACA_API_KEY, config.ALPACA_SECRET_KEY
        )

    def account_value(self):
        acct = self.trading.get_account()
        return float(acct.equity)

    def latest_price(self, symbol):
        req = StockLatestQuoteRequest(symbol_or_symbols=symbol)
        quote = self.data.get_stock_latest_quote(req)[symbol]
        # midpoint of bid/ask
        return (quote.bid_price + quote.ask_price) / 2

    def buy(self, symbol, qty):
        if config.DRY_RUN:
            return {"dry_run": True, "would": "buy", "symbol": symbol, "qty": qty}
        order = MarketOrderRequest(
            symbol=symbol, qty=qty, side=OrderSide.BUY, time_in_force=TimeInForce.DAY
        )
        return self.trading.submit_order(order)

    def sell(self, symbol, qty):
        if config.DRY_RUN:
            return {"dry_run": True, "would": "sell", "symbol": symbol, "qty": qty}
        order = MarketOrderRequest(
            symbol=symbol, qty=qty, side=OrderSide.SELL, time_in_force=TimeInForce.DAY
        )
        return self.trading.submit_order(order)

    def position_qty(self, symbol):
        for pos in self.trading.get_all_positions():
            if pos.symbol == symbol:
                return float(pos.qty)
        return 0.0

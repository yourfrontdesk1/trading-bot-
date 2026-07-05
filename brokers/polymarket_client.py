"""Read-only Polymarket client via the public gamma API.

Reading markets/prices needs no key. Placing real bets needs a wallet key and
the CLOB order API — we add that once the read side and a strategy are proven.
"""
import requests
import config


class PolymarketClient:
    def __init__(self):
        self.base = config.POLYMARKET_GAMMA_API

    def active_markets(self, limit=20):
        """Return currently open markets, most liquid first."""
        r = requests.get(
            f"{self.base}/markets",
            params={"active": "true", "closed": "false", "limit": limit,
                    "order": "volume", "ascending": "false"},
            timeout=15,
        )
        r.raise_for_status()
        return r.json()

    def market(self, market_id):
        r = requests.get(f"{self.base}/markets/{market_id}", timeout=15)
        r.raise_for_status()
        return r.json()

    @staticmethod
    def outcome_prices(market):
        """Pull (outcome, price) pairs out of a market dict. Prices are 0..1 probabilities."""
        import json
        outcomes = market.get("outcomes")
        prices = market.get("outcomePrices")
        if isinstance(outcomes, str):
            outcomes = json.loads(outcomes)
        if isinstance(prices, str):
            prices = json.loads(prices)
        if not outcomes or not prices:
            return []
        return list(zip(outcomes, [float(p) for p in prices]))

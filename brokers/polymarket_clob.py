"""Polymarket order execution — MAKER limit orders only, HARD-GATED.

The research is unambiguous: at £30 you MUST rest maker limit orders (fee-free),
never take market orders (fees eat the whole edge). This wraps py-clob-client.

SAFETY — this will NOT place a real order unless ALL of these are true:
  - config.DRY_RUN is False
  - a POLYMARKET_WALLET_KEY is set in .env (a BURNER wallet, never your main one)
  - py-clob-client is installed
Otherwise it logs the intended order and places nothing. Default state is safe:
DRY_RUN=true ships in .env, so this is inert until you deliberately arm it.

Setup when you're ready (and ONLY if Polymarket is accessible from Gibraltar):
  1. pip install py-clob-client
  2. Fund a FRESH burner Polygon wallet with ~$38 USDC (never a main wallet)
  3. Put its private key in .env as POLYMARKET_WALLET_KEY
  4. Approve USDC spending for the CLOB exchange (one-time on-chain)
  5. Flip DRY_RUN=false
"""
import config

try:
    from py_clob_client.client import ClobClient
    from py_clob_client.clob_types import OrderArgs, OrderType
    from py_clob_client.order_builder.constants import BUY
    _CLOB = True
except ImportError:
    _CLOB = False

HOST = "https://clob.polymarket.com"
CHAIN_ID = 137  # Polygon


def _armed():
    return (not config.DRY_RUN) and bool(config.POLYMARKET_WALLET_KEY) and _CLOB


def place_maker_bet(token_id: str, price: float, dollars: float):
    """Rest a fee-free GTC BUY limit order for `dollars` of `token_id` at `price`.

    Returns a dict describing what happened. Places NOTHING unless fully armed.
    """
    shares = round(dollars / price, 2) if price > 0 else 0
    intent = {"token_id": token_id, "price": price, "dollars": dollars,
              "shares": shares, "type": "GTC maker (fee-free)"}

    if shares < 5:
        return {"placed": False, "reason": "below 5-share minimum", **intent}
    if not _armed():
        reason = ("DRY_RUN on" if config.DRY_RUN else
                  "no burner wallet key" if not config.POLYMARKET_WALLET_KEY else
                  "py-clob-client not installed")
        return {"placed": False, "reason": f"safe mode ({reason}) — would rest this order", **intent}

    # ---- live path (only reached when deliberately armed) ----
    client = ClobClient(HOST, key=config.POLYMARKET_WALLET_KEY, chain_id=CHAIN_ID)
    client.set_api_creds(client.create_or_derive_api_creds())
    order = client.create_order(OrderArgs(
        token_id=token_id, price=price, size=shares, side=BUY))
    resp = client.post_order(order, OrderType.GTC)
    return {"placed": True, "response": resp, **intent}


if __name__ == "__main__":
    # dry demo — proves it stays safe
    print(place_maker_bet("0xDEMO", 0.20, 1.25))

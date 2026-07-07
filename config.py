"""Central config, loaded from .env. Nothing secret lives in code."""
import os
from dotenv import load_dotenv

load_dotenv()


def _bool(name, default):
    # Fail SAFE: a missing OR blank value keeps the (safe) default. A blank
    # `DRY_RUN=` line must never resolve to False and silently arm live trading.
    v = os.getenv(name)
    if v is None or not v.strip():
        return default
    return v.strip().lower() in ("1", "true", "yes")


# Alpaca (stocks)
ALPACA_API_KEY = os.getenv("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY", "")
ALPACA_PAPER = _bool("ALPACA_PAPER", True)

# Polymarket (prediction markets)
POLYMARKET_WALLET_KEY = os.getenv("POLYMARKET_WALLET_KEY", "")
POLYMARKET_GAMMA_API = "https://gamma-api.polymarket.com"

# Weather data. With a paid Open-Meteo key the bot uses the uncapped "customer-"
# endpoints and runs constantly; without it, the free tier's daily cap applies.
OPENMETEO_API_KEY = os.getenv("OPENMETEO_API_KEY", "")

# Bot behaviour
DRY_RUN = _bool("DRY_RUN", True)
POLL_SECONDS = int(os.getenv("POLL_SECONDS", "60"))

# Anthropic agent (agentic strategy)
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
AGENT_MODEL = os.getenv("AGENT_MODEL", "claude-opus-4-8")

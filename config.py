"""Central config, loaded from .env. Nothing secret lives in code."""
import os
from dotenv import load_dotenv

load_dotenv()


def _bool(name, default):
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes")


# Alpaca (stocks)
ALPACA_API_KEY = os.getenv("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY", "")
ALPACA_PAPER = _bool("ALPACA_PAPER", True)

# Polymarket (prediction markets)
POLYMARKET_WALLET_KEY = os.getenv("POLYMARKET_WALLET_KEY", "")
POLYMARKET_GAMMA_API = "https://gamma-api.polymarket.com"

# Bot behaviour
DRY_RUN = _bool("DRY_RUN", True)
POLL_SECONDS = int(os.getenv("POLL_SECONDS", "60"))

# Anthropic agent (agentic strategy)
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
AGENT_MODEL = os.getenv("AGENT_MODEL", "claude-opus-4-8")

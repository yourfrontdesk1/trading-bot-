# trading-bot

Trades **stocks** (Alpaca) and scans **prediction markets** (Polymarket).
Ships in safe mode: paper money + dry-run, so it can run today with zero risk.

## Setup

```bash
cd ~/trading-bot
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # then fill in your keys
```

## Get keys

- **Alpaca (stocks):** free at https://app.alpaca.markets/ -> Paper Trading -> API Keys.
  Paste into `ALPACA_API_KEY` / `ALPACA_SECRET_KEY`. Keep `ALPACA_PAPER=true`.
- **Polymarket:** reading markets needs no key. Placing bets comes later.

## Run

```bash
source venv/bin/activate
python bot.py
```

It loops every `POLL_SECONDS`: checks the stock watchlist, scans Polymarket for
long-shot outcomes, and logs what it *would* do.

## Safety switches (in `.env`)

| Setting | Safe value | What it does |
|---|---|---|
| `DRY_RUN` | `true` | Logs intended trades, places nothing |
| `ALPACA_PAPER` | `true` | Uses Alpaca fake-money account |

To actually place paper trades: set `DRY_RUN=false` (still fake money while
`ALPACA_PAPER=true`). Only set `ALPACA_PAPER=false` when you mean real money.

## Where to build next

- `strategies/example.py` — replace the toy rules with your real signal.
- `bot.py` `WATCHLIST` — the stocks it trades.
- Polymarket order placement (CLOB + wallet) — added once a strategy proves out.

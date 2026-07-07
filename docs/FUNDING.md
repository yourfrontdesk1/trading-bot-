# Funding & Cashing Out — plain-English guide

**Read this first:** the bot runs on paper by default. Nothing here is a "today"
step. This is the full money loop for *when* the paper track record proves a real
edge (a positive win-rate over 50–100 resolved bets). Until then, funding real
money is betting on an unproven model — don't.

## The two words you need
- **USDC** = a digital US dollar. 1 USDC = $1, always. Polymarket bets settle in USDC.
- **Polygon** = the payment "rail" USDC travels on for Polymarket. It's fast (seconds)
  and nearly free (pennies). The other rail, **Ethereum**, is slow and costs dollars,
  so Polymarket uses Polygon.

**The golden rule:** whenever you move USDC to or from Polymarket, set the network
to **Polygon** on BOTH ends. Send on Polygon to something expecting Ethereum and the
money is gone forever. This is the #1 way people lose funds.

## How money flows in (deposit)
1. Buy **USDC** on an exchange (Coinbase, Kraken, …).
2. Send it **on the Polygon network** to your Polymarket wallet address.
3. It arrives in ~1–5 minutes. Now you can bet.

## How money flows out (cash out)
1. **Free up the cash first:** you can only withdraw your *free* USDC. Money in open
   orders or held bet-shares is locked until you sell the shares or the market resolves
   (winning shares redeem for $1 each).
2. Polymarket **Portfolio → Withdraw**:
   - **Withdraw Crypto** → send USDC (on Polygon!) to your exchange, or
   - **Withdraw Cash** → off-ramp to bank/card via MoonPay (simpler, worse rates).
3. On the exchange: sell USDC for £/$, withdraw to your bank (1–3 business days).
- Fees are ~nil (Polymarket pays the gas). Crypto withdrawals land in minutes.

## Safety rules for this project (non-negotiable)
1. **Start with ~£30 (~$38), not your whole balance.** The bot is sized for $1–2 bets.
   The first real money is to test that orders actually place/fill — not to get rich.
   Prove the plumbing on a tiny amount before ever scaling up.
2. **Use a FRESH burner wallet**, funded with only what you're testing. Never a main
   wallet. If a key has ever been pasted into a chat/terminal, it's burned — make a new one.
3. **Verify Gibraltar is allowed** on Polymarket before depositing — the region rules
   apply to withdrawing too. Don't put money in that you can't cleanly take out.
4. **The bot never holds or moves your money.** It only signs bet orders against a
   wallet you fund and control. Cashing out is always your hand, not the bot's.

## What has to be true before any of this (the blockers, in order)
1. Paper track record shows a real edge (50–100 resolved bets, positive win-rate).
2. Python ≥3.9.10 so the order client installs (currently 3.9.6 — blocked).
3. Gibraltar trading permission confirmed.
4. A fresh, funded burner wallet; key entered by hand in `.env`.
5. `DRY_RUN=false` — thrown deliberately by you, on a tiny bankroll first.

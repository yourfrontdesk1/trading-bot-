"""Placeholder strategies so the bot does something visible on day one.

These are deliberately simple and NOT profitable advice. They exist to prove the
pipeline works end to end (read price -> decide -> place order in paper/dry-run).
Swap the `decide` logic for your real edge later.
"""


def stock_decision(symbol, price, held_qty):
    """Return ('buy', qty) | ('sell', qty) | ('hold', 0).

    Toy rule: hold a single share. Buy 1 if we own none, else do nothing.
    Replace with your actual signal (momentum, mean-reversion, news, etc.).
    """
    if held_qty == 0:
        return ("buy", 1)
    return ("hold", 0)


def prediction_scan(markets, price_fn):
    """Flag prediction markets where one outcome looks mispriced.

    Toy rule: surface any market whose top outcome trades under 0.10 (a long-shot).
    Returns a list of human-readable notes. No orders placed on Polymarket yet.
    """
    notes = []
    for m in markets:
        pairs = price_fn(m)
        if not pairs:
            continue
        cheapest = min(pairs, key=lambda op: op[1])
        outcome, prob = cheapest
        if prob < 0.10:
            notes.append(f"{m.get('question', '?')[:60]} -> '{outcome}' @ {prob:.2f}")
    return notes

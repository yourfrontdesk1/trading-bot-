"""8 AM daily 'morning pick' — today's single best bet + the running win ratio.

Reads the already-running dashboard API (no extra weather-API load), logs a dated
line to state/morning_picks.log, and fires a macOS notification so you see the
bet to place. Placement is still manual (£1) until live auto-trading is unblocked.
"""
import os
import json
import subprocess
import urllib.request
from datetime import datetime

STATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state")
LOG = os.path.join(STATE, "morning_picks.log")


def _log(line):
    os.makedirs(STATE, exist_ok=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def _notify(title, msg):
    try:
        subprocess.run(["osascript", "-e",
                        f'display notification "{msg}" with title "{title}"'],
                       timeout=10)
    except Exception:
        pass


def main():
    ts = f"{datetime.now():%Y-%m-%d %H:%M}"
    try:
        with urllib.request.urlopen("http://localhost:8090/api/weather-edge", timeout=150) as r:
            d = json.load(r)
    except Exception as e:
        line = f"{ts} | ERROR reaching bot: {e}"
        _log(line); print(line); _notify("Weather bot", "Couldn't reach the bot this morning")
        return

    picks = d.get("picks", [])
    # ONLY promote genuinely actionable bets. Watch-only candidates (esp. big edges
    # from single-source fallback) are artifacts, not recommendations.
    actionable = [p for p in picks if p.get("actionable")]
    status = d.get("data_status")
    led = d.get("ledger", {})
    week = f"week: {led.get('resolved', 0)} resolved, win {led.get('win_rate')}%"

    if not actionable:
        line = f"{ts} | NO BET today — nothing cleared the bar ({status}). {week}"
        _log(line); print(line); _notify("Weather bot — no bet today", week)
        return

    # surface EVERY actionable bet (best edge first), not just the top one
    actionable.sort(key=lambda r: -(r.get("edge") or 0))
    _log(f"{ts} | {len(actionable)} BET(S) TODAY ({status}) | {week}")
    print(f"{ts} | {len(actionable)} bet(s) today:")
    for b in actionable:
        headline = f"{b.get('best_side')} {b.get('city')} {b.get('threshold_c')}° @ {b.get('p_market')}"
        conf = b.get("confidence") or "?"
        detail = (f"    [{conf} confidence] {headline}\n"
                  f"       model says {round((b.get('model_prob') or 0)*100)}% vs market "
                  f"{round((b.get('p_market') or 0)*100)}% -> {round((b.get('edge') or 0)*100)}pt edge "
                  f"({b.get('members')} forecasts, {b.get('data_source')})\n"
                  f"       why: {b.get('reasoning', '')}\n"
                  f"       {b.get('poly_url')}")
        _log(detail); print(detail)
    top = actionable[0]
    _notify(f"Weather bot — {len(actionable)} bet(s) today",
            f"{top.get('best_side')} {top.get('city')} {top.get('threshold_c')}°"
            + (f" +{len(actionable)-1} more" if len(actionable) > 1 else ""))


if __name__ == "__main__":
    main()

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
    actionable = [p for p in picks if p.get("actionable")]
    pool = actionable or picks
    status = d.get("data_status")
    led = d.get("ledger", {})
    week = f"week: {led.get('resolved', 0)} resolved, win {led.get('win_rate')}%"

    if not pool:
        line = f"{ts} | NO BET today (no clear edge / {status}). {week}"
        _log(line); print(line); _notify("Weather bot — no bet today", week)
        return

    b = pool[0]
    tag = "ACTIONABLE" if b.get("actionable") else "watch-only"
    headline = f"{b.get('best_side')} {b.get('city')} {b.get('threshold_c')}° @ {b.get('p_market')}"
    line = (f"{ts} | TODAY'S £1 BET: {headline} | model {b.get('model_prob')} "
            f"edge {b.get('edge')} ({tag}, src {b.get('data_source')}, {status}) "
            f"| {b.get('poly_url')} | {week}")
    _log(line); print(line)
    _notify(f"Weather bot — {tag}", f"{headline}  (edge {b.get('edge')})")


if __name__ == "__main__":
    main()

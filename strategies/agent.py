"""Agentic strategy: an AI analyst that reads live context (news, filings,
sentiment) via web search and returns a structured trading view.

This is the one strategy with a shot at a real edge — it looks at information
price-only strategies can't see. It is NOT a guarantee of profit; every call is
still just a probabilistic opinion to be tested, not trusted.

Uses Claude (claude-opus-4-8 by default) with the web_search server tool +
adaptive thinking. Returns {direction, confidence, rationale, findings}.
"""
import json
import re
import subprocess

import config

# Runs through the local `claude` CLI (your Claude Code login) — NOT the paid
# Console API key. No per-token console charges.

_SYSTEM = """You are a disciplined trading analyst. You are given one instrument
(a stock or a prediction market) and must form a view using CURRENT, real-world
information you find via web search — recent news, earnings, guidance, sentiment,
catalysts, or (for weather/event markets) the relevant facts.

Rules:
- Search the web for current, dated information before deciding. Cite what you find.
- Be honest about uncertainty. Most of the time the right answer is HOLD / low confidence.
- You have no edge from price patterns alone; your only edge is information.
- Never fabricate. If you can't find good current info, say so and lower confidence.

End your response with EXACTLY one JSON object on its own, no prose after it:
{"direction": "buy|sell|hold",  // for prediction markets use "yes|no|hold"
 "confidence": 0.0-1.0,
 "rationale": "2-3 sentence plain-English reason",
 "findings": ["short dated fact 1", "short dated fact 2"]}"""


def _extract_json(text):
    # grab the last {...} block
    matches = re.findall(r"\{[\s\S]*\}", text)
    for m in reversed(matches):
        try:
            d = json.loads(m)
            if "direction" in d:
                return d
        except Exception:
            continue
    return None


def analyze(subject: str, kind: str = "stock", context: str = "") -> dict:
    """subject: e.g. 'NVDA' or a Polymarket question. Returns a decision dict.

    Uses the local `claude` CLI (your Claude Code session) with web search —
    no Console API key, no per-token charges.
    """
    label = "stock ticker" if kind == "stock" else "prediction market"
    prompt = (
        f"{_SYSTEM}\n\n---\nAnalyze this {label}: {subject}\n{context}\n"
        "Search the web for current information, then give your view for a short-term trade. "
        "Output ONLY the JSON object described above as your final message."
    )
    try:
        proc = subprocess.run(
            ["claude", "-p", prompt,
             "--allowedTools", "WebSearch,WebFetch",
             "--max-turns", "10"],
            capture_output=True, text=True, timeout=240,
        )
    except FileNotFoundError:
        return {"error": "claude CLI not found on PATH", "direction": "hold", "confidence": 0}
    except subprocess.TimeoutExpired:
        return {"error": "analysis timed out", "direction": "hold", "confidence": 0}

    text = (proc.stdout or "").strip()
    if not text:
        return {"error": (proc.stderr or "no output")[:200], "direction": "hold", "confidence": 0}
    parsed = _extract_json(text)
    if not parsed:
        return {"error": "no decision parsed", "raw": text[:300], "direction": "hold", "confidence": 0}
    parsed["model"] = "claude-code (local session)"
    return parsed


if __name__ == "__main__":
    import sys
    subj = sys.argv[1] if len(sys.argv) > 1 else "NVDA"
    out = analyze(subj, "stock", "Current price around $195.")
    print(json.dumps(out, indent=2))

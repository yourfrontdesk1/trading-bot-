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

import config

try:
    import anthropic
    _SDK = True
except ImportError:
    _SDK = False

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
    """subject: e.g. 'NVDA' or a Polymarket question. Returns a decision dict."""
    if not _SDK:
        return {"error": "anthropic SDK not installed"}
    if not config.ANTHROPIC_API_KEY:
        return {"error": "no ANTHROPIC_API_KEY in .env"}

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    label = "stock ticker" if kind == "stock" else "prediction market"
    user = f"Analyze this {label}: {subject}\n{context}\nForm a view for a short-term trade."

    messages = [{"role": "user", "content": user}]
    tools = [{"type": "web_search_20260209", "name": "web_search", "max_uses": 5}]

    final = None
    for _ in range(6):  # allow server-tool pause_turn continuations
        resp = client.messages.create(
            model=config.AGENT_MODEL,
            max_tokens=4000,
            thinking={"type": "adaptive"},
            system=_SYSTEM,
            tools=tools,
            messages=messages,
        )
        if resp.stop_reason == "pause_turn":
            messages = [{"role": "user", "content": user},
                        {"role": "assistant", "content": resp.content}]
            continue
        final = resp
        break

    if final is None:
        return {"error": "agent did not finish"}
    if final.stop_reason == "refusal":
        return {"error": "model refused", "direction": "hold", "confidence": 0}

    text = "".join(b.text for b in final.content if b.type == "text")
    parsed = _extract_json(text)
    if not parsed:
        return {"error": "no decision parsed", "raw": text[:300], "direction": "hold", "confidence": 0}
    parsed["model"] = config.AGENT_MODEL
    return parsed


if __name__ == "__main__":
    import sys
    subj = sys.argv[1] if len(sys.argv) > 1 else "NVDA"
    out = analyze(subj, "stock", "Current price around $195.")
    print(json.dumps(out, indent=2))

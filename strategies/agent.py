"""Agentic strategy: an AI analyst that reads live context (news, filings,
sentiment) via web search and returns a structured trading view.

This is the one strategy with a shot at a real edge — it looks at information
price-only strategies can't see. It is NOT a guarantee of profit; every call is
still just a probabilistic opinion to be tested, not trusted.

Runs on the **Claude Console API** (the official Anthropic SDK) with its own API
key, so it's a standalone agent — not tied to a personal `claude` CLI login. Set
ANTHROPIC_API_KEY in .env (from console.anthropic.com). Uses claude-opus-4-8 with
adaptive thinking + the server-side web_search tool. Returns
{direction, confidence, rationale, findings}.
"""
import json
import re

import config

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
    # grab the last {...} block that looks like our decision
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

    Uses the Claude Console API (paid, per-token) with server-side web search —
    a standalone agent that runs anywhere ANTHROPIC_API_KEY is set."""
    import anthropic

    if not config.ANTHROPIC_API_KEY:
        return {"error": "ANTHROPIC_API_KEY not set — add your Claude Console key to .env",
                "direction": "hold", "confidence": 0}

    label = "stock ticker" if kind == "stock" else "prediction market"
    prompt = (f"Analyze this {label}: {subject}\n{context}\n"
              "Search the web for current information, then give your view for a short-term trade. "
              "Output ONLY the JSON object described in the system prompt as your final message.")

    try:
        client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        messages = [{"role": "user", "content": prompt}]
        resp = None
        # server-side web search runs its own loop; resume on pause_turn (no extra
        # user message — the API detects the trailing server_tool_use and continues).
        for _ in range(6):
            resp = client.messages.create(
                model=config.AGENT_MODEL,          # claude-opus-4-8
                max_tokens=16000,
                system=_SYSTEM,
                thinking={"type": "adaptive"},
                tools=[{"type": "web_search_20260209", "name": "web_search"}],
                messages=messages,
            )
            if resp.stop_reason != "pause_turn":
                break
            messages.append({"role": "assistant", "content": resp.content})
        if resp is not None and resp.stop_reason == "refusal":
            return {"error": "model declined the request", "direction": "hold", "confidence": 0}
        text = "".join(b.text for b in resp.content if b.type == "text").strip()
    except anthropic.APIStatusError as e:
        return {"error": f"Claude API error {e.status_code}", "direction": "hold", "confidence": 0}
    except Exception as e:
        return {"error": str(e)[:200], "direction": "hold", "confidence": 0}

    if not text:
        return {"error": "no output", "direction": "hold", "confidence": 0}
    parsed = _extract_json(text)
    if not parsed:
        return {"error": "no decision parsed", "raw": text[:300], "direction": "hold", "confidence": 0}
    parsed["model"] = f"{config.AGENT_MODEL} (Claude Console API)"
    return parsed


if __name__ == "__main__":
    import sys
    subj = sys.argv[1] if len(sys.argv) > 1 else "NVDA"
    print(json.dumps(analyze(subj, "stock", "Current price around $195."), indent=2))

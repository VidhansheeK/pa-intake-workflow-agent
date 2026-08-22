"""LLM access layer.

Offline (deterministic) by default; Claude when ANTHROPIC_API_KEY is set.
Every call is JSON-schema-constrained via structured outputs, and any failure
(API error, safety refusal, missing key) returns None so callers use their
deterministic fallback — the pipeline always completes.

Env vars:
    ANTHROPIC_API_KEY  enables LLM mode
    PA_MODE=offline    forces offline mode even with a key
    PA_MODEL           model override (default claude-opus-5)
"""
import json
import os

MODEL = os.environ.get("PA_MODEL", "claude-opus-5")


def mode() -> str:
    if os.environ.get("PA_MODE") == "offline":
        return "offline"
    return "llm" if os.environ.get("ANTHROPIC_API_KEY") else "offline"


def complete_json(system: str, prompt: str, schema: dict) -> dict | None:
    """Ask Claude for a response matching `schema`. None => use offline fallback."""
    if mode() == "offline":
        return None
    try:
        import anthropic

        client = anthropic.Anthropic()
        response = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=system,
            messages=[{"role": "user", "content": prompt}],
            output_config={"format": {"type": "json_schema", "schema": schema}},
        )
        if response.stop_reason == "refusal":
            return None  # classifiers declined; deterministic fallback takes over
        text = next(b.text for b in response.content if b.type == "text")
        return json.loads(text)
    except Exception as e:  # any API failure degrades gracefully to offline
        print(f"[llm] falling back to offline path: {type(e).__name__}: {e}")
        return None

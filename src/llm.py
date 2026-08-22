"""LLM access layer.

Offline (deterministic) by default; uses a hosted model when a key is present.
Every call is JSON-schema-constrained, and any failure (API error, safety
refusal, missing key) returns None so callers use their deterministic
fallback — the pipeline always completes.

Providers (first match wins):
    ANTHROPIC_API_KEY  -> Claude (default model claude-opus-5)
    GEMINI_API_KEY     -> Google Gemini free tier (default gemini-2.5-flash)
    neither            -> offline

Env vars:
    PA_MODE=offline    forces offline mode even with a key
    PA_MODEL           model override for whichever provider is active
"""
import json
import os
import urllib.request

DEFAULT_MODELS = {"anthropic": "claude-opus-5", "gemini": "gemini-2.5-flash"}


def provider() -> str:
    if os.environ.get("PA_MODE") == "offline":
        return "offline"
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
        return "gemini"
    return "offline"


def mode() -> str:
    """'offline' or 'llm' — callers only branch on this."""
    return "offline" if provider() == "offline" else "llm"


def _model(prov: str) -> str:
    return os.environ.get("PA_MODEL", DEFAULT_MODELS[prov])


def _anthropic_json(system: str, prompt: str, schema: dict) -> dict | None:
    import anthropic

    client = anthropic.Anthropic()
    response = client.messages.create(
        model=_model("anthropic"),
        max_tokens=4096,
        system=system,
        messages=[{"role": "user", "content": prompt}],
        output_config={"format": {"type": "json_schema", "schema": schema}},
    )
    if response.stop_reason == "refusal":
        return None  # classifiers declined; deterministic fallback takes over
    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text)


def _strip_additional_properties(schema):
    """Gemini's responseSchema rejects 'additionalProperties'; drop it recursively."""
    if isinstance(schema, dict):
        return {k: _strip_additional_properties(v)
                for k, v in schema.items() if k != "additionalProperties"}
    if isinstance(schema, list):
        return [_strip_additional_properties(v) for v in schema]
    return schema


def _gemini_json(system: str, prompt: str, schema: dict) -> dict | None:
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    model = _model("gemini")
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{model}:generateContent?key={api_key}")
    body = {
        "system_instruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": _strip_additional_properties(schema),
        },
    }
    request = urllib.request.Request(
        url, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(request, timeout=90) as response:
        payload = json.loads(response.read())
    candidates = payload.get("candidates") or []
    if not candidates:  # safety-blocked or empty; use deterministic fallback
        return None
    text = candidates[0]["content"]["parts"][0]["text"]
    return json.loads(text)


def complete_json(system: str, prompt: str, schema: dict) -> dict | None:
    """Ask the active LLM for a response matching `schema`. None => offline fallback."""
    prov = provider()
    if prov == "offline":
        return None
    try:
        if prov == "anthropic":
            return _anthropic_json(system, prompt, schema)
        return _gemini_json(system, prompt, schema)
    except Exception as e:  # any API failure degrades gracefully to offline
        print(f"[llm:{prov}] falling back to offline path: {type(e).__name__}: {e}")
        return None

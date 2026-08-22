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
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_MODELS = {"anthropic": "claude-opus-5", "gemini": "gemini-3.5-flash-lite"}

# Measurement integrity: count calls served vs degraded, so evals can state
# whether an "LLM mode" run was actually all-LLM (see BUILD_LOG: silent
# fallbacks corrupted the first eval run).
CALLS = {"llm": 0, "fallback": 0}

# Load KEY=VALUE lines from the project's .env (gitignored) so keys work in the
# CLI, evals, and Streamlit without exporting. Real env vars take precedence.
_env_file = Path(__file__).parent.parent / ".env"
if _env_file.exists():
    for _line in _env_file.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _key, _, _value = _line.partition("=")
            os.environ.setdefault(_key.strip(), _value.strip().strip('"').strip("'"))


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
    # Free tier is ~10 requests/min: on 429, wait out Google's retryDelay
    # instead of falling back, so eval runs stay fully in LLM mode.
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                payload = json.loads(response.read())
            break
        except urllib.error.HTTPError as e:
            if e.code != 429 or attempt == 3:
                raise
            error_body = e.read().decode(errors="replace")
            match = re.search(r'"retryDelay":\s*"(\d+)', error_body)
            delay = int(match.group(1)) + 1 if match else 30
            print(f"[llm:gemini] rate limited; retrying in {delay}s")
            time.sleep(min(delay, 65))
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
        result = _anthropic_json(system, prompt, schema) if prov == "anthropic" \
            else _gemini_json(system, prompt, schema)
        CALLS["llm" if result is not None else "fallback"] += 1
        return result
    except Exception as e:  # any API failure degrades gracefully to offline
        CALLS["fallback"] += 1
        print(f"[llm:{prov}] falling back to offline path: {type(e).__name__}: {e}")
        return None

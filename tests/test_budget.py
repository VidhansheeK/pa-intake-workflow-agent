import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from src import llm  # noqa: E402


def test_budget_guard_blocks_before_any_network_call(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake")
    monkeypatch.delenv("PA_MODE", raising=False)
    monkeypatch.setattr(llm, "BUDGET_USD", 0.0)  # budget already exhausted
    calls_before = dict(llm.CALLS)
    result = llm.complete_json("s", "p", {"type": "object"})
    assert result is None  # degraded to offline, no exception, no network
    assert llm.CALLS["fallback"] == calls_before["fallback"] + 1


def test_call_cap_blocks_runaway_loop(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake")
    monkeypatch.delenv("PA_MODE", raising=False)
    monkeypatch.setattr(llm, "BUDGET_USD", 100.0)
    monkeypatch.setattr(llm, "MAX_LLM_CALLS", 0)  # cap already reached
    assert llm.complete_json("s", "p", {"type": "object"}) is None


def test_cost_recording_math(tmp_path, monkeypatch):
    monkeypatch.setattr(llm, "LEDGER_PATH", tmp_path / "ledger.jsonl")
    spent_before = llm.SPENT["usd"]
    llm._record_usage("claude-opus-5", 1_000_000, 1_000_000)  # $5 in + $25 out
    assert abs(llm.SPENT["usd"] - spent_before - 30.0) < 1e-9
    assert (tmp_path / "ledger.jsonl").exists()

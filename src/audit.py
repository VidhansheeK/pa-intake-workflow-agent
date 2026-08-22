"""Append-only JSONL audit log: who did what to which case, when."""
import json
from datetime import datetime, timezone
from pathlib import Path

LOG_PATH = Path(__file__).parent.parent / "audit_log.jsonl"


def log(case_id: str, action: str, actor: str = "system", details: dict | None = None) -> None:
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "case_id": case_id,
        "actor": actor,
        "action": action,
        "details": details or {},
    }
    with LOG_PATH.open("a") as f:
        f.write(json.dumps(entry) + "\n")

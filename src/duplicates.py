"""Duplicate-request detection.

A request is a possible duplicate when an EARLIER request exists for the same
member + same procedure within the lookback window. Only the later request is
flagged (the original proceeds normally). Deterministic by design — routing to
duplicate_review is a judgment a human makes at the gate, not the system.
"""
import json
from datetime import datetime, timedelta
from pathlib import Path

PACKETS_DIR = Path(__file__).parent.parent / "data" / "packets"
LOOKBACK_DAYS = 14


def check(packet: dict, packets_dir: Path = PACKETS_DIR) -> list[dict]:
    member_id = packet.get("member", {}).get("member_id")
    cpt = packet.get("request", {}).get("procedure_cpt")
    received = packet.get("received_at")
    if not (member_id and cpt and received):
        return []  # identity findings are already raised by completeness
    received_dt = datetime.fromisoformat(received)

    # ponytail: O(n) scan over the corpus per case — index by (member, cpt)
    # when volume matters.
    for path in sorted(packets_dir.glob("PA-*.json")):
        other = json.loads(path.read_text())
        if other["case_id"] == packet.get("case_id"):
            continue
        if (other.get("member", {}).get("member_id") == member_id
                and other.get("request", {}).get("procedure_cpt") == cpt
                and other.get("received_at")):
            other_dt = datetime.fromisoformat(other["received_at"])
            if other_dt < received_dt <= other_dt + timedelta(days=LOOKBACK_DAYS):
                return [{
                    "code": "possible_duplicate",
                    "severity": "warning",
                    "detail": (f"Same member and procedure as {other['case_id']} "
                               f"received {(received_dt - other_dt).days} day(s) earlier."),
                    "source": "rule",
                }]
    return []

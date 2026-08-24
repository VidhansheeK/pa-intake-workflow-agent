import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from src import duplicates  # noqa: E402


def write_packet(tmp_path, case_id, member_id, cpt, received_at):
    packet = {"case_id": case_id, "received_at": received_at,
              "member": {"member_id": member_id},
              "request": {"procedure_cpt": cpt}}
    (tmp_path / f"{case_id}.json").write_text(json.dumps(packet))
    return packet


def test_later_request_is_flagged_earlier_is_not(tmp_path):
    first = write_packet(tmp_path, "PA-1", "M1", "27447", "2026-08-10T09:00:00")
    second = write_packet(tmp_path, "PA-2", "M1", "27447", "2026-08-12T09:00:00")
    assert duplicates.check(first, tmp_path) == []
    findings = duplicates.check(second, tmp_path)
    assert len(findings) == 1 and findings[0]["code"] == "possible_duplicate"
    assert "PA-1" in findings[0]["detail"]


def test_outside_lookback_window_not_flagged(tmp_path):
    write_packet(tmp_path, "PA-1", "M1", "27447", "2026-07-01T09:00:00")
    late = write_packet(tmp_path, "PA-2", "M1", "27447", "2026-08-12T09:00:00")
    assert duplicates.check(late, tmp_path) == []


def test_different_cpt_or_member_not_flagged(tmp_path):
    write_packet(tmp_path, "PA-1", "M1", "27447", "2026-08-10T09:00:00")
    other_cpt = write_packet(tmp_path, "PA-2", "M1", "70553", "2026-08-11T09:00:00")
    other_member = write_packet(tmp_path, "PA-3", "M2", "27447", "2026-08-11T09:00:00")
    assert duplicates.check(other_cpt, tmp_path) == []
    assert duplicates.check(other_member, tmp_path) == []

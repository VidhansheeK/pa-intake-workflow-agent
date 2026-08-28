import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from src import followups  # noqa: E402

PACKET = {
    "case_id": "PA-TEST-0042",
    "provider": {"name": "Dr. Test"},
    "request": {"procedure_description": "MRI brain"},
}
FINDINGS = [
    {"code": "member_id_missing", "severity": "blocking", "detail": "No member ID."},
    {"code": "clinical_notes_insufficient", "severity": "blocking",
     "detail": "Clinical documentation incomplete: no mention of symptom duration."},
]


def test_template_letter_covers_every_finding_and_passes_rubric(monkeypatch):
    monkeypatch.setenv("PA_MODE", "offline")
    draft = followups.draft(PACKET, FINDINGS)
    assert draft["source"] == "template"
    assert followups._verify(draft, PACKET, FINDINGS) == []
    assert "PA-TEST-0042" in draft["letter"]
    assert len(draft["questions"]) == len(FINDINGS)


def test_verify_catches_uncovered_finding():
    bad = {"questions": [{"finding_code": "member_id_missing", "question": "ID?"}],
           "letter": "RE: PA-TEST-0042 ..."}
    problems = followups._verify(bad, PACKET, FINDINGS)
    assert any("not addressed" in p for p in problems)


def test_verify_catches_invented_finding_and_missing_case_id():
    bad = {"questions": [{"finding_code": "member_id_missing", "question": "ID?"},
                         {"finding_code": "clinical_notes_insufficient", "question": "Notes?"},
                         {"finding_code": "made_up_requirement", "question": "Extra?"}],
           "letter": "Dear Provider, send more stuff."}
    problems = followups._verify(bad, PACKET, FINDINGS)
    assert any("do not exist" in p for p in problems)
    assert any("case ID" in p for p in problems)

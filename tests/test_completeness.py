import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from src import completeness  # noqa: E402


def make_packet(**overrides):
    members = json.loads((ROOT / "data" / "members.json").read_text())
    packet = {
        "case_id": "PA-TEST-0001",
        "member": {"member_id": members[0]["member_id"], "name": "Test", "dob": "1970-01-01"},
        "provider": {"npi": "1234567893", "name": "Dr. Test"},  # valid Luhn NPI
        "request": {"procedure_cpt": "99213", "diagnosis_icd10": "E11.9",
                    "urgency": "standard", "expedited_justification": None},
        "clinical_notes": "Routine follow-up.",
    }
    for key, value in overrides.items():
        if isinstance(value, dict):
            packet[key].update(value)
        else:
            packet[key] = value
    return packet


def codes(packet):
    return {f["code"] for f in completeness.check(packet)}


def test_valid_npi_luhn():
    assert completeness.valid_npi("1234567893")       # known-valid checksum
    assert not completeness.valid_npi("1234567890")   # bad check digit
    assert not completeness.valid_npi("12345")        # wrong length
    assert not completeness.valid_npi("abcdefghij")   # not digits
    assert not completeness.valid_npi(None)


def test_generator_npis_pass_validation():
    # guards against the generator's Luhn and the validator's Luhn diverging
    labels = json.loads((ROOT / "data" / "golden_labels.json").read_text())
    for case_id, label in labels.items():
        if "fax" in label:  # fax cases live in data/faxes, not data/packets
            continue
        if "npi_invalid" in label["expected_findings"] or "member_id_missing" in label["expected_findings"]:
            continue
        packet = json.loads((ROOT / "data" / "packets" / f"{case_id}.json").read_text())
        assert completeness.valid_npi(packet["provider"]["npi"]), case_id


def test_complete_packet_has_no_findings():
    assert codes(make_packet()) == set()


def test_missing_member_id():
    assert "member_id_missing" in codes(make_packet(member={"member_id": None}))


def test_member_not_found():
    assert "member_not_found" in codes(make_packet(member={"member_id": "M999999999"}))


def test_missing_diagnosis_and_bad_icd():
    assert "diagnosis_missing" in codes(make_packet(request={"diagnosis_icd10": None}))
    assert "diagnosis_invalid" in codes(make_packet(request={"diagnosis_icd10": "11.9"}))


def test_expedited_without_justification():
    packet = make_packet(request={"urgency": "expedited", "expedited_justification": None})
    assert "expedited_justification_missing" in codes(packet)


def test_clinical_notes_keyword_fallback(monkeypatch):
    monkeypatch.setenv("PA_MODE", "offline")
    packet = make_packet(
        request={"procedure_cpt": "27447", "diagnosis_icd10": "M17.11"},
        clinical_notes="Knee pain for two years. X-ray shows joint space narrowing. BMI 30.",
    )  # notes omit conservative therapy
    assert "clinical_notes_insufficient" in codes(packet)


def test_empty_notes_on_pa_required_cpt():
    packet = make_packet(request={"procedure_cpt": "27447", "diagnosis_icd10": "M17.11"},
                         clinical_notes="")
    assert "clinical_notes_missing" in codes(packet)

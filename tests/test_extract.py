import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from src import extract  # noqa: E402

FAX = """UHC PRIOR AUTHORIZATION REQUEST — FAX TRANSMISSION
Reference: PA-TEST-0077
Received: 2026-08-20T10:00:00
Member ID: M123456789
Member Name: Test Person
Member DOB: 1970-05-05
Plan: UHC Choice Plus
Provider NPI: 1234567893
Provider Name: Dr. Test
Provider Phone: +1-555-000-1111
Procedure (CPT): 27447 - Total knee arthroplasty
Diagnosis (ICD-10): M17.11 - Osteoarthritis, right knee
Urgency: standard

CLINICAL NOTES:
Physical therapy for 4 months. X-ray shows joint space narrowing. BMI 30.
"""


def test_regex_extraction_full(monkeypatch):
    monkeypatch.setenv("PA_MODE", "offline")
    packet = extract.extract_from_text(FAX)
    assert packet["case_id"] == "PA-TEST-0077"
    assert packet["member"]["member_id"] == "M123456789"
    assert packet["provider"]["npi"] == "1234567893"
    assert packet["request"]["procedure_cpt"] == "27447"
    assert packet["request"]["diagnosis_icd10"] == "M17.11"
    assert "Physical therapy" in packet["clinical_notes"]
    assert packet["extraction_source"] == "regex"


def test_missing_field_becomes_none_not_guess(monkeypatch):
    monkeypatch.setenv("PA_MODE", "offline")
    fax = "\n".join(l for l in FAX.splitlines() if not l.startswith("Diagnosis"))
    packet = extract.extract_from_text(fax)
    assert packet["request"]["diagnosis_icd10"] is None


def test_gemini_schema_conversion_is_api_compatible():
    """Gemini rejects JSON-Schema unions and additionalProperties with HTTP 400."""
    from src import llm
    converted = llm._to_gemini_schema(extract.EXTRACT_SCHEMA)
    assert "additionalProperties" not in converted
    case_id = converted["properties"]["case_id"]
    assert case_id == {"type": "string", "nullable": True}, case_id

    def no_union_types(node):
        if isinstance(node, dict):
            assert not isinstance(node.get("type"), list), f"union type left in: {node}"
            for v in node.values():
                no_union_types(v)
        elif isinstance(node, list):
            for v in node:
                no_union_types(v)
    no_union_types(converted)

"""Completeness checks for a PA intake packet.

Deterministic wherever a rule can decide (field presence, NPI checksum, code
format, eligibility lookup); the LLM is used only where language understanding
is required — judging whether free-text clinical notes satisfy the CPT's
policy requirements — with a keyword heuristic as the offline fallback.
"""
import json
import re
from pathlib import Path

from . import llm

DATA_DIR = Path(__file__).parent.parent / "data"
ICD10_RE = re.compile(r"^[A-Z]\d{2}(\.\d{1,4})?$")
CPT_RE = re.compile(r"^([0-9]{5}|[A-Z][0-9]{4})$")

CLINICAL_SCHEMA = {
    "type": "object",
    "properties": {
        "unmet_requirements": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"id": {"type": "string"}, "reason": {"type": "string"}},
                "required": ["id", "reason"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["unmet_requirements"],
    "additionalProperties": False,
}


def load_policies() -> dict:
    return json.loads((DATA_DIR / "policies.json").read_text())


def load_members() -> dict:
    return {m["member_id"]: m for m in json.loads((DATA_DIR / "members.json").read_text())}


def valid_npi(npi) -> bool:
    """Real NPI check: Luhn over '80840' + first 9 digits, 10th is check digit."""
    if not npi or not isinstance(npi, str) or not npi.isdigit() or len(npi) != 10:
        return False
    digits = [int(d) for d in "80840" + npi[:9]]
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 0:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return str((10 - total % 10) % 10) == npi[9]


def _finding(code: str, severity: str, detail: str) -> dict:
    return {"code": code, "severity": severity, "detail": detail}


def check_clinical_notes(notes: str, policy: dict) -> list[dict]:
    """Return unmet clinical requirements. LLM judges semantics; offline uses keywords."""
    requirements = policy.get("clinical_requirements", [])
    if not requirements:
        return []

    result = llm.complete_json(
        system=(
            "You are a prior-authorization intake completeness checker. "
            "Given clinical notes and a list of policy requirements, decide which "
            "requirements are NOT satisfied by the notes. Be strict: a requirement "
            "is met only if the notes explicitly document it. Never invent "
            "requirements that are not in the list."
        ),
        prompt=(
            f"Clinical notes:\n{notes}\n\nPolicy requirements:\n"
            + "\n".join(f"- id={r['id']}: {r['text']}" for r in requirements)
            + "\n\nReturn the unmet requirements (empty list if all are met)."
        ),
        schema=CLINICAL_SCHEMA,
    )
    if result is not None:
        known = {r["id"] for r in requirements}
        return [u for u in result["unmet_requirements"] if u["id"] in known]

    # ponytail: offline fallback is a keyword heuristic — LLM mode does the real
    # semantic check; upgrade path is better keywords per policies.json.
    lowered = notes.lower()
    return [
        {"id": r["id"], "reason": f"no mention of: {r['text']}"}
        for r in requirements
        if not any(k in lowered for k in r["keywords"])
    ]


def check(packet: dict, policies: dict | None = None, members: dict | None = None) -> list[dict]:
    """Run all completeness checks. Returns a list of findings (empty = complete)."""
    policies = policies if policies is not None else load_policies()
    members = members if members is not None else load_members()
    findings = []

    member = packet.get("member", {})
    member_id = member.get("member_id")
    if not member_id:
        findings.append(_finding("member_id_missing", "blocking", "No member ID on the request."))
    elif member_id not in members:
        findings.append(_finding("member_not_found", "blocking",
                                 f"Member ID {member_id} not found in eligibility."))
    if not member.get("dob"):
        findings.append(_finding("member_dob_missing", "blocking", "Member date of birth missing."))

    npi = packet.get("provider", {}).get("npi")
    if not npi:
        findings.append(_finding("npi_missing", "blocking", "No provider NPI on the request."))
    elif not valid_npi(npi):
        findings.append(_finding("npi_invalid", "blocking", f"Provider NPI '{npi}' fails validation."))

    request = packet.get("request", {})
    cpt = request.get("procedure_cpt")
    policy = policies.get(cpt) if cpt else None
    if not cpt:
        findings.append(_finding("cpt_missing", "blocking", "No procedure code on the request."))
    elif not CPT_RE.match(cpt) or policy is None:
        findings.append(_finding("cpt_unknown", "blocking", f"Procedure code '{cpt}' not recognized."))

    icd = request.get("diagnosis_icd10")
    if not icd:
        findings.append(_finding("diagnosis_missing", "blocking", "No diagnosis code on the request."))
    elif not ICD10_RE.match(icd):
        findings.append(_finding("diagnosis_invalid", "blocking",
                                 f"Diagnosis code '{icd}' is not a valid ICD-10 format."))

    if request.get("urgency") == "expedited" and not request.get("expedited_justification"):
        findings.append(_finding("expedited_justification_missing", "blocking",
                                 "Expedited review requested without clinical justification."))

    # Clinical-notes checks only matter when the procedure actually needs PA review.
    if policy and policy.get("pa_required"):
        notes = packet.get("clinical_notes") or ""
        if not notes.strip():
            findings.append(_finding("clinical_notes_missing", "blocking",
                                     "Clinical notes are empty."))
        else:
            unmet = check_clinical_notes(notes, policy)
            if unmet:
                detail = "; ".join(u["reason"] for u in unmet)
                findings.append(_finding("clinical_notes_insufficient", "blocking",
                                         f"Clinical documentation incomplete: {detail}"))
    return findings

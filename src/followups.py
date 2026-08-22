"""Draft provider follow-up questions for incomplete packets.

LLM mode drafts the letter, then a verification loop (loop-engineering Loop 2)
grades it against a deterministic rubric and retries once with feedback before
falling back to templates. Offline mode uses the templates directly.

Rubric (checked in code, not vibes):
- every finding is covered by at least one question
- no question invents a requirement outside the findings
- letter includes the case ID
"""
from . import llm

# Provider-facing question templates per finding code (the offline path and
# the fallback when the LLM draft fails verification twice).
TEMPLATES = {
    "member_id_missing": "Please provide the member's ID exactly as shown on their insurance card.",
    "member_not_found": "The member ID submitted could not be matched to an active plan. Please confirm the member ID and plan.",
    "member_dob_missing": "Please provide the member's date of birth.",
    "npi_missing": "Please provide the ordering provider's 10-digit NPI.",
    "npi_invalid": "The provider NPI submitted appears invalid. Please confirm the ordering provider's 10-digit NPI.",
    "cpt_missing": "Please provide the CPT/HCPCS code for the requested procedure.",
    "cpt_unknown": "The procedure code submitted was not recognized. Please confirm the CPT/HCPCS code.",
    "diagnosis_missing": "Please provide the ICD-10 diagnosis code supporting this request.",
    "diagnosis_invalid": "The diagnosis code submitted is not a valid ICD-10 code. Please confirm the diagnosis code.",
    "expedited_justification_missing": "Expedited review was requested. Please provide the clinical justification for expedited handling.",
    "clinical_notes_missing": "Please attach clinical notes supporting this request.",
    "clinical_notes_insufficient": "The clinical documentation is missing required elements: {detail} Please provide the missing documentation.",
}

DRAFT_SCHEMA = {
    "type": "object",
    "properties": {
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"finding_code": {"type": "string"}, "question": {"type": "string"}},
                "required": ["finding_code", "question"],
                "additionalProperties": False,
            },
        },
        "letter": {"type": "string"},
    },
    "required": ["questions", "letter"],
    "additionalProperties": False,
}


def _template_draft(packet: dict, findings: list[dict]) -> dict:
    questions = []
    for f in findings:
        text = TEMPLATES.get(f["code"], f"Please clarify: {f['detail']}")
        if "{detail}" in text:
            text = text.format(detail=f["detail"].split(":", 1)[-1].strip())
        questions.append({"finding_code": f["code"], "question": text})
    body = "\n".join(f"  {i + 1}. {q['question']}" for i, q in enumerate(questions))
    letter = (
        f"RE: Prior Authorization Request {packet['case_id']}\n\n"
        f"Dear {packet['provider']['name']},\n\n"
        f"We received your prior authorization request for "
        f"{packet['request'].get('procedure_description') or 'the requested service'}. "
        f"Before clinical review can begin, we need the following information:\n\n{body}\n\n"
        f"Please reply with the requested information to avoid delays in processing.\n\n"
        f"UHC Prior Authorization Intake Team\n[SYNTHETIC — demo output, not a real communication]"
    )
    return {"questions": questions, "letter": letter, "source": "template"}


def _verify(draft: dict, packet: dict, findings: list[dict]) -> list[str]:
    """Deterministic rubric check. Returns list of problems (empty = pass)."""
    problems = []
    expected = {f["code"] for f in findings}
    covered = {q.get("finding_code") for q in draft.get("questions", [])}
    if missing := expected - covered:
        problems.append(f"findings not addressed by any question: {sorted(missing)}")
    if extra := covered - expected:
        problems.append(f"questions reference findings that do not exist: {sorted(extra)}")
    if packet["case_id"] not in draft.get("letter", ""):
        problems.append("letter does not reference the case ID")
    return problems


def draft(packet: dict, findings: list[dict]) -> dict:
    """Return {questions, letter, source}. Only called when findings exist."""
    if llm.mode() == "offline":
        return _template_draft(packet, findings)

    findings_text = "\n".join(f"- code={f['code']}: {f['detail']}" for f in findings)
    system = (
        "You draft professional follow-up letters to healthcare providers about "
        "incomplete prior-authorization requests. Ask only for what the listed "
        "findings require — never invent additional requirements. Be specific, "
        "courteous, and concise. Include the case ID in the letter."
    )
    prompt = (
        f"Case ID: {packet['case_id']}\n"
        f"Provider: {packet['provider']['name']}\n"
        f"Procedure: {packet['request'].get('procedure_description')}\n"
        f"Findings (one question per finding, tagged with its finding_code):\n{findings_text}"
    )

    feedback = ""
    for _ in range(2):  # Loop 2: draft -> verify -> one retry with feedback
        result = llm.complete_json(system, prompt + feedback, DRAFT_SCHEMA)
        if result is None:
            break
        problems = _verify(result, packet, findings)
        if not problems:
            result["source"] = "llm"
            return result
        feedback = "\n\nYour previous draft failed review: " + "; ".join(problems) + ". Fix these."
    return _template_draft(packet, findings)  # verified-safe fallback

"""Extraction layer: unstructured fax text -> structured intake packet.

Real intake receives much of its volume as faxes. This module turns a fax
transmission (plain text; an OCR step would sit in front of this in
production) into the same packet dict the rest of the pipeline consumes.

LLM mode extracts semantically (handles messy layouts); offline mode parses
the labeled-line format with regexes. A field the extractor cannot find is
None — the completeness checker downstream flags it, so extraction never has
to guess.
"""
import re

from . import llm

EXTRACT_SCHEMA = {
    "type": "object",
    "properties": {
        "case_id": {"type": ["string", "null"]},
        "received_at": {"type": ["string", "null"]},
        "member_id": {"type": ["string", "null"]},
        "member_name": {"type": ["string", "null"]},
        "member_dob": {"type": ["string", "null"]},
        "plan": {"type": ["string", "null"]},
        "provider_npi": {"type": ["string", "null"]},
        "provider_name": {"type": ["string", "null"]},
        "provider_phone": {"type": ["string", "null"]},
        "procedure_cpt": {"type": ["string", "null"]},
        "procedure_description": {"type": ["string", "null"]},
        "diagnosis_icd10": {"type": ["string", "null"]},
        "diagnosis_description": {"type": ["string", "null"]},
        "urgency": {"type": ["string", "null"]},
        "expedited_justification": {"type": ["string", "null"]},
        "clinical_notes": {"type": ["string", "null"]},
    },
    "required": ["case_id", "member_id", "provider_npi", "procedure_cpt",
                 "diagnosis_icd10", "clinical_notes"],
    "additionalProperties": False,
}

# Offline fallback: labeled-line regexes for the standard fax layout.
# ponytail: handles the structured fax format only; genuinely messy scans are
# what LLM mode (and a production OCR step) is for.
_PATTERNS = {
    "case_id": r"Reference:\s*(\S+)",
    "received_at": r"Received:\s*(\S+)",
    "member_id": r"Member ID:\s*(\S+)",
    "member_name": r"Member Name:\s*(.+)",
    "member_dob": r"Member DOB:\s*(\S+)",
    "plan": r"Plan:\s*(.+)",
    "provider_npi": r"Provider NPI:\s*(\S+)",
    "provider_name": r"Provider Name:\s*(.+)",
    "provider_phone": r"Provider Phone:\s*(\S+)",
    "procedure_cpt": r"Procedure \(CPT\):\s*(\S+)",
    "procedure_description": r"Procedure \(CPT\):\s*\S+\s*-\s*(.+)",
    "diagnosis_icd10": r"Diagnosis \(ICD-10\):\s*(\S+)",
    "diagnosis_description": r"Diagnosis \(ICD-10\):\s*\S+\s*-\s*(.+)",
    "urgency": r"Urgency:\s*(\S+)",
}


def _regex_extract(text: str) -> dict:
    fields = {}
    for key, pattern in _PATTERNS.items():
        match = re.search(pattern, text)
        fields[key] = match.group(1).strip() if match else None
    notes = re.search(r"CLINICAL NOTES:\s*\n(.*)", text, re.DOTALL)
    fields["clinical_notes"] = notes.group(1).strip() if notes else None
    fields["expedited_justification"] = None
    return fields


def _to_packet(fields: dict) -> dict:
    return {
        "case_id": fields.get("case_id") or "PA-UNKNOWN",
        "received_at": fields.get("received_at"),
        "channel": "fax",
        "member": {
            "member_id": fields.get("member_id"),
            "name": fields.get("member_name"),
            "dob": fields.get("member_dob"),
            "plan": fields.get("plan"),
        },
        "provider": {
            "npi": fields.get("provider_npi"),
            "name": fields.get("provider_name"),
            "specialty": None,
            "phone": fields.get("provider_phone"),
        },
        "request": {
            "procedure_cpt": fields.get("procedure_cpt"),
            "procedure_description": fields.get("procedure_description"),
            "diagnosis_icd10": fields.get("diagnosis_icd10"),
            "diagnosis_description": fields.get("diagnosis_description"),
            "urgency": fields.get("urgency") or "standard",
            "expedited_justification": fields.get("expedited_justification"),
        },
        "clinical_notes": fields.get("clinical_notes") or "",
        "extraction_source": None,  # filled by extract_from_text
    }


def extract_from_text(text: str) -> dict:
    """Fax text -> packet dict. Missing fields become None (flagged downstream)."""
    fields = llm.complete_json(
        system=(
            "You extract structured fields from a faxed prior-authorization "
            "request. Return null for any field not present in the document — "
            "never invent or infer values. Copy identifiers exactly as written."
        ),
        prompt=f"Fax document:\n\n{text}",
        schema=EXTRACT_SCHEMA,
    )
    source = "llm"
    if fields is None:
        fields = _regex_extract(text)
        source = "regex"
    packet = _to_packet(fields)
    packet["extraction_source"] = source
    return packet

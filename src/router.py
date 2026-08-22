"""Deterministic routing rules — auditable by design, no LLM in the routing decision.

Priority order:
1. CPT known and PA not required        -> no_auth_required (auto-close letter)
2. Member found-but-ineligible issues   -> eligibility_review (internal team)
3. Any other finding                    -> provider_outreach (with follow-up letter)
4. Complete + expedited                 -> expedited_clinical_review::<specialty>
5. Complete + standard                  -> clinical_review::<specialty>
"""

INTERNAL_FINDINGS = {"member_not_found"}  # resolvable internally, not by the provider


def route(packet: dict, findings: list[dict], policies: dict) -> dict:
    cpt = packet.get("request", {}).get("procedure_cpt")
    policy = policies.get(cpt) if cpt else None

    if policy and not policy["pa_required"]:
        return {"queue": "no_auth_required",
                "reason": f"CPT {cpt} does not require prior authorization."}

    codes = {f["code"] for f in findings}
    if codes & INTERNAL_FINDINGS:
        return {"queue": "eligibility_review",
                "reason": "Member could not be matched to eligibility; needs internal review."}
    if codes:
        return {"queue": "provider_outreach",
                "reason": f"Request incomplete ({len(codes)} issue(s)); provider follow-up required."}

    specialty = policy["specialty_queue"] if policy else "general"
    if packet.get("request", {}).get("urgency") == "expedited":
        return {"queue": f"expedited_clinical_review::{specialty}",
                "reason": "Complete expedited request; priority clinical review."}
    return {"queue": f"clinical_review::{specialty}",
            "reason": "Complete request; standard clinical review."}

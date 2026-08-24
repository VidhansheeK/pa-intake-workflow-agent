"""End-to-end intake pipeline: (extract) -> completeness -> follow-ups -> route.

Nothing leaves the system without human approval: the pipeline only *proposes*
(findings, letter, route); approval happens in the review app (app/review_app.py)
or via the CLI gate here, and every decision lands in the audit log.

CLI:
    python -m src.pipeline PA-2026-0003            # process one case, print proposal
    python -m src.pipeline PA-2026-0003 --approve  # interactive human approval gate
    python -m src.pipeline --fax data/faxes/FAX-0001.txt   # unstructured fax entry
    python -m src.pipeline --all                   # process every packet (no approvals)
"""
import json
import sys
from pathlib import Path

from . import audit, completeness, duplicates, extract, followups, llm, router

PACKETS_DIR = Path(__file__).parent.parent / "data" / "packets"
PROPOSALS_DIR = Path(__file__).parent.parent / "data" / "proposals"


def load_packet(case_id: str) -> dict:
    return json.loads((PACKETS_DIR / f"{case_id}.json").read_text())


def process(packet: dict, policies: dict | None = None, members: dict | None = None) -> dict:
    """Run the pipeline for one packet. Returns the full proposal (pending approval)."""
    policies = policies if policies is not None else completeness.load_policies()
    members = members if members is not None else completeness.load_members()

    findings = completeness.check(packet, policies, members)
    findings += duplicates.check(packet)
    decision = router.route(packet, findings, policies)
    result = {
        "case_id": packet["case_id"],
        "mode": llm.provider(),
        "channel": packet.get("channel"),
        "extraction_source": packet.get("extraction_source"),
        "findings": findings,
        "route": decision,
        "followup": None,
        "status": "pending_approval",
        "est_llm_cost_usd": round(llm.SPENT["usd"], 6),
    }
    if decision["queue"] == "provider_outreach":
        result["followup"] = followups.draft(packet, findings)

    audit.log(packet["case_id"], "pipeline_proposal", actor=f"pipeline({llm.provider()})",
              details={"findings": [f["code"] for f in findings], "route": decision["queue"]})
    return result


def store_proposal(result: dict) -> None:
    PROPOSALS_DIR.mkdir(exist_ok=True)
    (PROPOSALS_DIR / f"{result['case_id']}.json").write_text(json.dumps(result, indent=2))


def load_proposal(case_id: str) -> dict | None:
    path = PROPOSALS_DIR / f"{case_id}.json"
    return json.loads(path.read_text()) if path.exists() else None


def record_decision(case_id: str, approved: bool, reviewer: str, edits: str | None = None) -> None:
    """The human approval gate — the only path that finalizes a case."""
    audit.log(case_id, "approved" if approved else "rejected", actor=reviewer,
              details={"letter_edited": bool(edits)})


def _print(result: dict) -> None:
    print(f"\n=== {result['case_id']} (mode: {result['mode']}) ===")
    if result["findings"]:
        print("Findings:")
        for f in result["findings"]:
            print(f"  - [{f['code']}] {f['detail']}")
    else:
        print("Findings: none — packet complete")
    print(f"Proposed route: {result['route']['queue']}  ({result['route']['reason']})")
    if result["followup"]:
        print(f"\nDrafted follow-up letter ({result['followup']['source']}):\n")
        print(result["followup"]["letter"])


def main() -> None:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return
    if args[0] == "--all":
        for path in sorted(PACKETS_DIR.glob("PA-*.json")):
            result = process(json.loads(path.read_text()))
            print(f"{result['case_id']}: {len(result['findings'])} finding(s) "
                  f"-> {result['route']['queue']}")
        return

    if args[0] == "--fax":
        packet = extract.extract_from_text(Path(args[1]).read_text())
        print(f"Extracted packet from fax (source: {packet['extraction_source']})")
        result = process(packet)
        _print(result)
        return

    result = process(load_packet(args[0]))
    _print(result)
    if "--approve" in args:
        answer = input("\nApprove this proposal? [y/N/e(dit letter)] ").strip().lower()
        if answer == "e" and result["followup"]:
            print("Enter revised letter (end with a blank line):")
            lines = iter(input, "")
            edited = "\n".join(lines)
            record_decision(result["case_id"], True, "cli_reviewer", edits=edited)
            print("Approved with edited letter. Logged to audit_log.jsonl.")
        elif answer == "y":
            record_decision(result["case_id"], True, "cli_reviewer")
            print("Approved. Logged to audit_log.jsonl.")
        else:
            record_decision(result["case_id"], False, "cli_reviewer")
            print("Rejected. Logged to audit_log.jsonl.")


if __name__ == "__main__":
    main()

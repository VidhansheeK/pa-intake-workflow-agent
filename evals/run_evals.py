"""Evaluate the pipeline against the golden labels.

Metrics:
- Missing-info detection: micro precision / recall / F1 over finding codes
- Routing accuracy: proposed queue vs expected queue
- Follow-up letters: rubric pass rate (every finding covered, no invented asks,
  case ID present) on every case routed to provider_outreach

Run:  python evals/run_evals.py            (offline deterministic mode)
      ANTHROPIC_API_KEY=... python evals/run_evals.py   (LLM mode)
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from src import completeness, extract, followups, llm, pipeline  # noqa: E402


def main() -> None:
    labels = json.loads((ROOT / "data" / "golden_labels.json").read_text())
    policies = completeness.load_policies()
    members = completeness.load_members()

    tp = fp = fn = 0
    route_hits = 0
    letters_checked = letters_passed = 0
    failures = []
    per_case = []

    for case_id, label in sorted(labels.items()):
        if "fax" in label:  # fax cases exercise the extraction layer end-to-end
            packet = extract.extract_from_text(
                (ROOT / "data" / "faxes" / label["fax"]).read_text())
        else:
            packet = pipeline.load_packet(case_id)
        result = pipeline.process(packet, policies, members)

        predicted = {f["code"] for f in result["findings"]}
        expected = set(label["expected_findings"])
        tp += len(predicted & expected)
        fp += len(predicted - expected)
        fn += len(expected - predicted)

        route_ok = result["route"]["queue"] == label["expected_route"]
        route_hits += route_ok

        if result["followup"]:
            letters_checked += 1
            problems = followups._verify(result["followup"], packet, result["findings"])
            letters_passed += not problems

        per_case.append({
            "case_id": case_id,
            "scenario": label["scenario"],
            "channel": "fax" if "fax" in label else "portal",
            "expected_findings": sorted(expected),
            "detected_findings": sorted(predicted),
            "findings_match": predicted == expected,
            "expected_route": label["expected_route"],
            "actual_route": result["route"]["queue"],
            "route_match": route_ok,
            "letter_source": (result["followup"] or {}).get("source"),
        })

        if predicted != expected or not route_ok:
            failures.append(
                f"  {case_id} [{label['scenario']}]: "
                f"findings {sorted(predicted)} vs expected {sorted(expected)}; "
                f"route {result['route']['queue']} vs expected {label['expected_route']}"
            )

    n = len(labels)
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0

    print(f"\n=== Eval results ({n} cases, mode: {llm.provider()}) ===")
    if llm.provider() != "offline":
        total = llm.CALLS["llm"] + llm.CALLS["fallback"]
        purity = llm.CALLS["llm"] / total if total else 0
        print(f"LLM call integrity:      {llm.CALLS['llm']}/{total} served by LLM "
              f"({purity:.0%} — below 100% means offline fallbacks diluted this run)")
    print(f"Missing-info detection:  precision {precision:.2%}  recall {recall:.2%}  F1 {f1:.2%}")
    print(f"Routing accuracy:        {route_hits}/{n} ({route_hits / n:.2%})")
    if letters_checked:
        print(f"Follow-up rubric pass:   {letters_passed}/{letters_checked} "
              f"({letters_passed / letters_checked:.2%})")
    if failures:
        print("\nFailures:")
        print("\n".join(failures))
    else:
        print("\nNo failures.")

    (ROOT / "evals" / "results.json").write_text(json.dumps({
        "mode": llm.provider(), "cases": n, "llm_calls": dict(llm.CALLS),
        "finding_precision": precision, "finding_recall": recall, "finding_f1": f1,
        "routing_accuracy": route_hits / n,
        "letter_rubric_pass_rate": (letters_passed / letters_checked) if letters_checked else None,
        "letters_checked": letters_checked,
        "letters_passed": letters_passed,
        "failures": failures,
        "per_case": per_case,
    }, indent=2))
    print("\nWritten to evals/results.json")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()

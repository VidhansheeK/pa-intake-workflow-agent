"""Human-in-the-loop review console for PA intake proposals.

Tabs: Review Queue (approve/edit/reject with pipeline trace), Dashboard
(queue stats + LLM cost/budget), Audit Trail, Evals. Nothing is finalized
without a human decision; every decision lands in the audit log.

Run:  streamlit run app/review_app.py
Optionally alongside:  python -m src.watcher   (event-driven intake)
"""
import difflib
import json
import sys
import time
from collections import Counter
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from src import audit, extract, llm, pipeline  # noqa: E402

DECISIONS_PATH = ROOT / "data" / "decisions.json"
LEDGER_PATH = ROOT / "data" / "cost_ledger.jsonl"
AUDIT_PATH = ROOT / "audit_log.jsonl"
RESULTS_PATH = ROOT / "evals" / "results.json"

BADGES = {"rule": "⚙️ RULE", "llm": "🤖 AI", "heuristic": "🔍 HEURISTIC (offline)"}

FIELD_CHECKS = [
    ("Member ID", ("member", "member_id"), {"member_id_missing", "member_not_found"}),
    ("Member DOB", ("member", "dob"), {"member_dob_missing"}),
    ("Provider NPI", ("provider", "npi"), {"npi_missing", "npi_invalid"}),
    ("Procedure (CPT)", ("request", "procedure_cpt"), {"cpt_missing", "cpt_unknown"}),
    ("Diagnosis (ICD-10)", ("request", "diagnosis_icd10"),
     {"diagnosis_missing", "diagnosis_invalid"}),
    ("Expedited justification", ("request", "expedited_justification"),
     {"expedited_justification_missing"}),
    ("Clinical notes", ("clinical_notes",),
     {"clinical_notes_missing", "clinical_notes_insufficient"}),
    ("Duplicate check", None, {"possible_duplicate"}),
]

st.set_page_config(page_title="PA Intake Review", page_icon="📋", layout="wide")


def load_decisions() -> dict:
    return json.loads(DECISIONS_PATH.read_text()) if DECISIONS_PATH.exists() else {}


def save_decision(case_id: str, decision: dict) -> None:
    decisions = load_decisions()
    decisions[case_id] = decision
    DECISIONS_PATH.write_text(json.dumps(decisions, indent=2))


def get_proposal(case_id: str) -> dict:
    stored = pipeline.load_proposal(case_id)
    if stored:
        return stored
    result = pipeline.process(pipeline.load_packet(case_id))
    pipeline.store_proposal(result)
    return result


def read_jsonl(path: Path, limit: int = 200) -> list[dict]:
    if not path.exists():
        return []
    lines = path.read_text().strip().splitlines()
    return [json.loads(line) for line in lines[-limit:]]


def field_value(packet: dict, keys) -> str:
    value = packet
    for key in keys:
        value = value.get(key) if isinstance(value, dict) else None
    if value is None or value == "":
        return "—"
    return (str(value)[:80] + "…") if len(str(value)) > 80 else str(value)


# ---------- header ----------
st.title("Prior Authorization Intake — Review Console")
st.caption(f"Mode: **{llm.provider()}** · Budget: **${llm.BUDGET_USD:.2f}** · "
           "All data synthetic · Nothing is finalized without your approval")

tab_queue, tab_dash, tab_audit, tab_evals = st.tabs(
    ["📋 Review Queue", "📊 Dashboard", "🧾 Audit Trail", "🎯 Evals"])

decisions = load_decisions()
case_ids = sorted(p.stem for p in (ROOT / "data" / "packets").glob("PA-*.json"))
pending = [c for c in case_ids if c not in decisions]

# ---------- tab 1: review queue ----------
with tab_queue:
    # bumping this key resets the uploader widget, clearing the file and the
    # status messages so the panel returns to its compact state
    round_no = st.session_state.get("upload_round", 0)

    with st.expander("📤 **Upload a new request** (fax .txt or packet .json)", expanded=False):
        st.caption("Drop a document here and watch it move through the pipeline into "
                   "the queue. Sample files live in `data/faxes/`.")
        uploaded = st.file_uploader("Choose a file", type=["txt", "json"],
                                    label_visibility="collapsed",
                                    key=f"uploader_{round_no}")

        if uploaded is not None:
            fingerprint = f"{uploaded.name}:{uploaded.size}"
            if st.session_state.get("processed_upload") != fingerprint:
                with st.status(f"Processing **{uploaded.name}**…", expanded=True) as status:
                    raw = uploaded.getvalue().decode("utf-8", errors="replace")

                    st.write(f"📥 **Received** · {uploaded.name} ({uploaded.size:,} bytes)")
                    time.sleep(0.35)

                    if uploaded.name.lower().endswith(".txt"):
                        st.write("📠 **Extracting fields from the document…**")
                        packet = extract.extract_from_text(raw)
                        st.write(f"✅ **Extracted** · via {packet['extraction_source']} · "
                                 f"case {packet['case_id']}")
                    else:
                        packet = json.loads(raw)
                        packet.setdefault("channel", "portal")
                        st.write(f"📄 **Structured packet read** · case {packet['case_id']}")
                    time.sleep(0.35)

                    # register it so it joins the queue and duplicate detection sees it
                    (ROOT / "data" / "packets" / f"{packet['case_id']}.json").write_text(
                        json.dumps(packet, indent=2))
                    audit.log(packet["case_id"], "ingested", actor="review_app_upload",
                              details={"file": uploaded.name,
                                       "extraction": packet.get("extraction_source")})

                    icons = {"Completeness checks": "🔍", "Duplicate check": "👯",
                             "Routing": "🧭", "Follow-up letter drafted": "✉️"}

                    def show(label, detail):
                        st.write(f"{icons.get(label, '•')} **{label}** · {detail}")
                        time.sleep(0.35)

                    result = pipeline.process(packet, on_step=show)
                    pipeline.store_proposal(result)

                    st.write("🧑‍⚖️ **Queued for human review**")
                    status.update(label=f"✅ {packet['case_id']} is in the queue "
                                        f"→ {result['route']['queue']}", state="complete")

                st.session_state.processed_upload = fingerprint
                st.session_state.last_case = packet["case_id"]

            st.success(f"**{st.session_state.get('last_case', '')}** is in the queue. "
                       "Refresh to see it and clear this panel.")
            if st.button("↻ Refresh queue", type="primary"):
                st.session_state.upload_round = round_no + 1  # resets the uploader
                st.session_state.pop("processed_upload", None)
                st.rerun()

    left, right = st.columns([1, 2.6])

    with left:
        top = st.columns([2, 1])
        top[0].subheader(f"Queue ({len(pending)} pending)")
        if top[1].button("🔄 Refresh"):
            st.rerun()
        selected = st.radio(
            "Select a case", case_ids,
            format_func=lambda c: f"{'✅' if c in decisions else '🔲'} {c}",
            label_visibility="collapsed",
        )

    with right:
        packet = pipeline.load_packet(selected)
        result = get_proposal(selected)
        findings = result["findings"]
        codes = {f["code"] for f in findings}

        st.subheader(selected)

        # --- pipeline trace stepper ---
        steps = st.columns(5)
        if packet.get("channel") == "fax" and result.get("extraction_source"):
            steps[0].success(f"📠 Extracted\n\n({result['extraction_source']})")
        else:
            steps[0].info("📥 Structured\n\nintake")
        if findings:
            steps[1].warning(f"🔎 Checks\n\n{len(findings)} finding(s)")
        else:
            steps[1].success("🔎 Checks\n\ncomplete")
        if result["followup"]:
            steps[2].warning(f"✉️ Letter\n\n({result['followup']['source']})")
        else:
            steps[2].info("✉️ Letter\n\nnot needed")
        steps[3].info(f"🧭 Route\n\n{result['route']['queue'].split('::')[0]}")
        if selected in decisions:
            decided = decisions[selected]["decision"]
            (steps[4].success if decided == "approved" else steps[4].error)(
                f"🧑‍⚖️ Human\n\n{decided}")
        else:
            steps[4].warning("🧑‍⚖️ Human\n\npending")

        st.markdown(f"**Routing reason:** {result['route']['reason']}")

        # --- findings with rule/AI badges ---
        if findings:
            st.markdown("**Findings**")
            for f in findings:
                badge = BADGES.get(f.get("source", "rule"), "⚙️ RULE")
                st.warning(f"**{badge}** · `{f['code']}` — {f['detail']}")
        else:
            st.success("Packet complete — no findings.")

        # --- packet field check table (highlights) ---
        with st.expander("Packet field checks", expanded=bool(findings)):
            for label, keys, related in FIELD_CHECKS:
                flagged = bool(codes & related)
                value = field_value(packet, keys) if keys else ""
                icon = "🔴" if flagged else "🟢"
                st.markdown(f"{icon} **{label}**: {value if keys else ('flagged' if flagged else 'clear')}")
        with st.expander("Raw packet JSON"):
            st.json(packet)

        # --- decision block ---
        if selected in decisions:
            d = decisions[selected]
            st.info(f"Decision recorded: **{d['decision']}** by {d['reviewer']}"
                    + (" (letter edited)" if d.get("letter_edited") else ""))
        else:
            letter = None
            if result["followup"]:
                st.markdown(f"**Drafted follow-up letter** (source: "
                            f"{result['followup']['source']}) — edit if needed:")
                letter = st.text_area("Letter", result["followup"]["letter"],
                                      height=260, label_visibility="collapsed")
                if letter != result["followup"]["letter"]:
                    with st.expander("✏️ Your changes vs the draft", expanded=True):
                        diff = difflib.unified_diff(
                            result["followup"]["letter"].splitlines(),
                            letter.splitlines(),
                            fromfile="draft", tofile="edited", lineterm="")
                        st.code("\n".join(diff), language="diff")

            reviewer = st.text_input("Reviewer name", value="reviewer")
            col_a, col_r = st.columns(2)
            if col_a.button("✅ Approve", type="primary", use_container_width=True):
                edited = bool(letter and result["followup"]
                              and letter != result["followup"]["letter"])
                pipeline.record_decision(selected, True, reviewer,
                                         edits=letter if edited else None)
                save_decision(selected, {"decision": "approved", "reviewer": reviewer,
                                         "letter_edited": edited})
                st.rerun()
            if col_r.button("❌ Reject", use_container_width=True):
                pipeline.record_decision(selected, False, reviewer)
                save_decision(selected, {"decision": "rejected", "reviewer": reviewer})
                st.rerun()

# ---------- tab 2: dashboard ----------
with tab_dash:
    st.subheader("Queue overview")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total cases", len(case_ids))
    m2.metric("Pending", len(pending))
    m3.metric("Approved", sum(d["decision"] == "approved" for d in decisions.values()))
    m4.metric("Rejected", sum(d["decision"] == "rejected" for d in decisions.values()))

    routes = Counter()
    for case_id in case_ids:
        try:
            routes[get_proposal(case_id)["route"]["queue"].split("::")[0]] += 1
        except FileNotFoundError:
            pass
    if routes:
        st.markdown("**Cases per proposed route**")
        st.bar_chart(dict(routes), horizontal=True)

    st.divider()
    st.subheader("Agent cost control")
    ledger = read_jsonl(LEDGER_PATH, limit=100000)
    spent = sum(entry["est_cost_usd"] for entry in ledger)
    tokens_in = sum(entry["input_tokens"] for entry in ledger)
    tokens_out = sum(entry["output_tokens"] for entry in ledger)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("LLM calls metered", len(ledger))
    c2.metric("Tokens in / out", f"{tokens_in:,} / {tokens_out:,}")
    c3.metric("Est. spend (list price)", f"${spent:.4f}")
    c4.metric("Budget (per run)", f"${llm.BUDGET_USD:.2f}")
    st.progress(min(spent / llm.BUDGET_USD, 1.0) if llm.BUDGET_USD else 0.0,
                text=f"Cumulative metered spend vs one run's budget — the guard degrades "
                     f"the agent to offline rules at the cap (plus a "
                     f"{llm.MAX_LLM_CALLS}-call runaway breaker)")
    st.caption("Free-tier Gemini bills $0 in reality; spend is metered at list price "
               "so the figure is meaningful for production sizing.")

# ---------- tab 3: audit trail ----------
with tab_audit:
    st.subheader("Audit trail (append-only)")
    entries = read_jsonl(AUDIT_PATH, limit=50)
    if entries:
        rows = [{"time": e["timestamp"][:19], "case": e["case_id"], "actor": e["actor"],
                 "action": e["action"], "details": json.dumps(e["details"])}
                for e in reversed(entries)]
        st.dataframe(rows, use_container_width=True, height=480)
        st.caption(f"Showing latest {len(entries)} entries from audit_log.jsonl — "
                   "every proposal and every human decision, with actor and timestamp.")
    else:
        st.info("No audit entries yet — process a case first.")

# ---------- tab 4: evals ----------
with tab_evals:
    st.subheader("Latest eval run")
    if RESULTS_PATH.exists():
        results = json.loads(RESULTS_PATH.read_text())
        e1, e2, e3, e4 = st.columns(4)
        e1.metric("Detection F1", f"{results['finding_f1']:.0%}")
        e2.metric("Routing accuracy", f"{results['routing_accuracy']:.0%}")
        rubric = results.get("letter_rubric_pass_rate")
        e3.metric("Letter rubric", f"{rubric:.0%}" if rubric is not None else "n/a")
        calls = results.get("llm_calls", {})
        total = calls.get("llm", 0) + calls.get("fallback", 0)
        e4.metric("LLM call integrity",
                  f"{calls.get('llm', 0)}/{total}" if total else "offline run")
        st.caption(f"Mode: {results['mode']} · {results['cases']} cases · "
                   "Run `python evals/run_evals.py` to refresh.")
        if results.get("failures"):
            st.error("\n".join(results["failures"]))
        else:
            st.success("No failures in the latest run.")
    else:
        st.info("No results yet — run `python evals/run_evals.py` first.")

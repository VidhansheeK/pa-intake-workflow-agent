"""Human-in-the-loop review queue for PA intake proposals.

Every case the pipeline processes lands here as a *proposal*. A human reviewer
approves, edits the follow-up letter, or rejects — nothing is finalized without
this step, and every decision is written to the audit log.

Run:  streamlit run app/review_app.py
"""
import json
import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from src import completeness, llm, pipeline  # noqa: E402

DECISIONS_PATH = ROOT / "data" / "decisions.json"

st.set_page_config(page_title="PA Intake Review", page_icon="📋", layout="wide")


def load_decisions() -> dict:
    return json.loads(DECISIONS_PATH.read_text()) if DECISIONS_PATH.exists() else {}


def save_decision(case_id: str, decision: dict) -> None:
    decisions = load_decisions()
    decisions[case_id] = decision
    DECISIONS_PATH.write_text(json.dumps(decisions, indent=2))


@st.cache_data
def run_pipeline(case_id: str) -> dict:
    packet = pipeline.load_packet(case_id)
    return pipeline.process(packet)


st.title("Prior Authorization Intake — Review Queue")
st.caption(f"Pipeline mode: **{llm.mode()}** · All data is synthetic · "
           "Nothing is finalized without your approval")

decisions = load_decisions()
case_ids = sorted(p.stem for p in (ROOT / "data" / "packets").glob("PA-*.json"))
pending = [c for c in case_ids if c not in decisions]

left, right = st.columns([1, 2.5])

with left:
    st.subheader(f"Queue ({len(pending)} pending)")
    selected = st.radio(
        "Select a case",
        case_ids,
        format_func=lambda c: f"{'✅' if c in decisions else '🔲'} {c}",
        label_visibility="collapsed",
    )

with right:
    packet = pipeline.load_packet(selected)
    result = run_pipeline(selected)

    st.subheader(selected)
    meta1, meta2, meta3 = st.columns(3)
    meta1.metric("Procedure", packet["request"].get("procedure_cpt") or "—")
    meta2.metric("Urgency", packet["request"].get("urgency", "—"))
    meta3.metric("Proposed queue", result["route"]["queue"].split("::")[0])

    st.markdown(f"**Routing reason:** {result['route']['reason']}")

    if result["findings"]:
        st.markdown("**Findings**")
        for f in result["findings"]:
            st.warning(f"`{f['code']}` — {f['detail']}")
    else:
        st.success("Packet complete — no findings.")

    with st.expander("Raw packet"):
        st.json(packet)

    if selected in decisions:
        d = decisions[selected]
        st.info(f"Decision recorded: **{d['decision']}** by {d['reviewer']}")
    else:
        letter = None
        if result["followup"]:
            st.markdown(f"**Drafted follow-up letter** (source: {result['followup']['source']}) "
                        "— edit before approving if needed:")
            letter = st.text_area("Letter", result["followup"]["letter"], height=280,
                                  label_visibility="collapsed")

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

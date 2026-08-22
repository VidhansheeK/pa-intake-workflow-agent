# Prior Authorization Intake Workflow Agent

FDE Cohort 5 Capstone — Track 2. An AI-assisted workflow that reviews synthetic
prior-authorization intake packets, detects missing information, drafts provider
follow-up questions, routes each case, and **preserves a human approval step**
for every decision.

**All data in this repository is synthetic.** No production data, no PHI.

## What it does

```
packet (JSON) ──▶ completeness check ──▶ follow-up drafting ──▶ routing ──▶ HUMAN APPROVAL ──▶ audit log
                  deterministic rules      LLM + verification     rule-based    review app /       JSONL
                  + LLM clinical check     loop (or templates)    decision      CLI gate
                                                                  table
```

- **Deterministic where a rule can decide** — field presence, NPI Luhn checksum,
  ICD-10 format, eligibility lookup, routing. Auditable, testable, free.
- **LLM only where language understanding is needed** — judging whether free-text
  clinical notes satisfy the CPT's policy requirements, and drafting the provider
  follow-up letter (verified against a rubric before a human ever sees it).
- **Runs with zero API keys** — offline mode uses deterministic fallbacks for the
  LLM steps, so any reviewer can execute the full pipeline, tests, and evals.

## Quick start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# regenerate the synthetic dataset (26 packets, 13 scenarios, golden labels)
python data/generate_packets.py

# process one case from the CLI
python -m src.pipeline PA-2026-0012            # incomplete: missing member ID
python -m src.pipeline PA-2026-0001            # complete: routes to clinical review
python -m src.pipeline PA-2026-0012 --approve  # with interactive approval gate

# run the review queue UI (the human approval step)
streamlit run app/review_app.py

# run evals against the golden labels
python evals/run_evals.py

# run tests
pytest tests/
```

### LLM mode (optional)

```bash
export ANTHROPIC_API_KEY=sk-ant-...   # enables Claude for clinical-notes checks
python -m src.pipeline PA-2026-0018   # and follow-up letter drafting
```

Without a key (or with `PA_MODE=offline`) every LLM step degrades gracefully to
its deterministic fallback. Model defaults to `claude-opus-5`; override with
`PA_MODEL`.

## Repository map

| Path | What it is |
|---|---|
| `data/generate_packets.py` | Synthetic data generator (seeded, reproducible) |
| `data/policies.json` | Per-CPT PA policy: required clinical elements, specialty queue |
| `data/packets/` | 26 synthetic intake packets across 13 scenarios |
| `data/golden_labels.json` | Ground truth per case (expected findings + route) — used only by evals |
| `src/completeness.py` | Missing-info detection (rules + LLM clinical check) |
| `src/followups.py` | Follow-up letter drafting + rubric verification loop |
| `src/router.py` | Deterministic routing decision table |
| `src/pipeline.py` | Orchestrator + CLI |
| `src/audit.py` | Append-only JSONL audit log |
| `app/review_app.py` | Streamlit human-approval review queue |
| `evals/run_evals.py` | Precision/recall/F1, routing accuracy, letter rubric pass rate |
| `tests/` | pytest suite for validators, router, letter rubric |
| `DESIGN.md` | Problem, requirements, architecture, enterprise readiness |
| `BUILD_LOG.md` | Running log of problems, rejected strategies, decisions |
| `AI_USAGE.md` | How AI was used to build this, and where humans stayed in the loop |

## Current eval results (offline mode, 26 cases)

Missing-info detection precision/recall/F1: **100% / 100% / 100%** · Routing
accuracy: **26/26** · Follow-up rubric pass rate: **15/15**. Offline mode is a
*consistency* check of the deterministic path against by-construction labels;
LLM-mode results and their failure modes are discussed in `DESIGN.md`.

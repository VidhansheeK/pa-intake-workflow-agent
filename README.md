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

Two providers are supported behind the same interface. Put your key in a `.env`
file at the project root (gitignored — see `.env.example`):

```bash
cp .env.example .env
# edit .env and paste ONE key:
#   GEMINI_API_KEY=AIza...     FREE tier key from https://aistudio.google.com/apikey
#   ANTHROPIC_API_KEY=sk-...   paid alternative (default model claude-opus-5)

python -m src.pipeline PA-2026-0018   # clinical-notes check + letter drafting via LLM
python evals/run_evals.py             # score LLM mode against the golden set
```

If both keys are set, Anthropic wins. Without any key (or with
`PA_MODE=offline`) every LLM step degrades gracefully to its deterministic
fallback. Override the model with `PA_MODEL`.

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

## Current eval results (26 cases)

| Mode | Missing-info P / R / F1 | Routing | Letter rubric | LLM call integrity |
|---|---|---|---|---|
| offline (deterministic) | 100% / 100% / 100% | 26/26 | 15/15 | n/a |
| LLM (`gemini-3.5-flash-lite`) | 100% / 100% / 100% | 26/26 | 15/15 | 38/38 served by LLM |

Offline mode is a *consistency* check of the deterministic path against
by-construction labels. The **LLM call integrity** column exists because an
earlier "LLM mode" run was silently diluted by offline fallbacks under rate
limiting — the eval now proves which path served every call (see
`BUILD_LOG.md`). Failure modes and limitations are discussed in `DESIGN.md`.

# Prior Authorization Intake Workflow Agent

FDE Cohort 5 Capstone — Track 2. An AI-assisted workflow that reviews synthetic
prior-authorization intake packets, detects missing information, drafts provider
follow-up questions, routes each case, and **preserves a human approval step**
for every decision.

**All data in this repository is synthetic.** No production data, no PHI.

## What it does

```
fax (.txt) ──▶ extraction ─┐
               LLM/regex   ├─▶ completeness ──▶ duplicate ──▶ follow-up ──▶ routing ──▶ HUMAN ──▶ audit
packet (JSON) ─────────────┘   rules + LLM      check         drafting +    decision    APPROVAL   log
   │                           clinical check   (rule)        verify loop   table       (app/CLI)  JSONL
   └── or drop into data/inbox/ — the watcher processes arrivals event-driven
```

Cross-cutting: a **cost guard** meters every LLM call (tokens + list-price
cost to `data/cost_ledger.jsonl`) and hard-stops at a budget (`PA_BUDGET_USD`,
default $1) plus a runaway-loop call cap — the agent degrades to offline rules
instead of overspending.

- **Deterministic where a rule can decide** — field presence, NPI Luhn checksum,
  ICD-10 format, eligibility lookup, routing. Auditable, testable, free.
- **LLM only where language understanding is needed** — judging whether free-text
  clinical notes satisfy the CPT's policy requirements, and drafting the provider
  follow-up letter (verified against a rubric before a human ever sees it).
- **Runs with zero API keys** — offline mode uses deterministic fallbacks for the
  LLM steps, so any reviewer can execute the full pipeline, tests, and evals.

## How to run this (start here)

**Requirements:** Python 3.10 or newer. Nothing else — **no API key, no database,
no Docker, no internet connection needed.**

### Step 1 — Get the code and install (about 1 minute)

```bash
git clone https://github.com/VidhansheeK/pa-intake-workflow-agent.git
cd pa-intake-workflow-agent

python3 -m venv .venv                 # create an isolated environment
source .venv/bin/activate             # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### Step 2 — Verify it works (about 30 seconds)

```bash
pytest tests/            # expect: 26 passed
python evals/run_evals.py   # expect: 100% detection, 29/29 routing, 16/16 rubric
```

If both pass, everything is working. You are in **offline mode**, where the two
AI steps use deterministic fallbacks — this is intentional, so the whole project
is reviewable without any API key.

### Step 3 — See the pipeline handle single cases

```bash
python -m src.pipeline PA-2026-0001    # complete packet -> routed to clinical review
python -m src.pipeline PA-2026-0012    # missing member ID -> follow-up letter drafted
python -m src.pipeline PA-2026-0018    # clinical notes missing the required TB screening
python -m src.pipeline PA-2026-0027    # duplicate of an earlier request -> duplicate queue
python -m src.pipeline --fax data/faxes/FAX-0002.txt   # starts from an unstructured fax
```

Each prints the findings, the proposed route with its reason, and the drafted
letter. Nothing is finalized — these are proposals awaiting human approval.

### Step 4 — Open the review console (the human approval gate)

```bash
streamlit run app/review_app.py
```

Opens at http://localhost:8501 with four tabs:

| Tab | What to look at |
|---|---|
| **Review Queue** | Pick a case. The stepper shows its path through the pipeline; each finding is badged ⚙️ RULE or 🤖 AI; edit the letter (a diff appears) and Approve or Reject |
| **Dashboard** | Queue counts, cases per route, and the LLM cost meter vs its budget cap |
| **Audit Trail** | Append-only log of every proposal and every human decision |
| **Evals** | Metrics from the most recent `run_evals.py` run |

### Step 5 — Optional: event-driven intake

In a **second terminal** (leave the app running in the first):

```bash
source .venv/bin/activate
python -m src.watcher                  # watches data/inbox/
```

Then in a third terminal — or any file manager — drop a document in:

```bash
cp data/faxes/FAX-0001.txt data/inbox/
```

The watcher extracts it, runs the pipeline, and it appears in the review queue.
Press Ctrl-C to stop the watcher.

### Step 6 — Optional: turn on real AI

Everything above runs without AI. To enable the two LLM steps (clinical-notes
judgment and letter drafting), add **one** key to a `.env` file:

```bash
cp .env.example .env
```

Then edit `.env` and paste one line:

```
GEMINI_API_KEY=AIza...        # free key from https://aistudio.google.com/apikey
```
or
```
ANTHROPIC_API_KEY=sk-ant-...  # paid alternative
```

Re-run any command above — the output header changes from `mode: offline` to
`mode: gemini`, and letters show `source: llm`. Spend is metered per call and
hard-capped by `PA_BUDGET_USD` (default $1); at the cap the agent degrades back
to offline rules rather than overspending.

### Troubleshooting

| Symptom | Fix |
|---|---|
| `command not found: python` | Use `python3` (macOS/Linux ship Python 3 under that name) |
| `ModuleNotFoundError` | The virtualenv isn't active — re-run `source .venv/bin/activate` |
| `streamlit: command not found` | Same cause: activate the venv, or run `python -m streamlit run app/review_app.py` |
| Port 8501 already in use | `streamlit run app/review_app.py --server.port 8502` |
| Want to reset the demo state | `rm -rf data/proposals data/decisions.json audit_log.jsonl` |
| Want to regenerate the dataset | `python data/generate_packets.py` (seeded — reproduces the same 27 packets + 2 faxes) |

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
| `src/extract.py` | Fax text → structured packet (LLM extraction, regex fallback) |
| `src/duplicates.py` | Duplicate-request detection (same member + CPT in 14 days) |
| `src/followups.py` | Follow-up letter drafting + rubric verification loop |
| `src/router.py` | Deterministic routing decision table (6 queues) |
| `src/pipeline.py` | Orchestrator + CLI |
| `src/watcher.py` | Event-driven intake: data/inbox → pipeline → review queue |
| `src/audit.py` | Append-only JSONL audit log |
| `app/review_app.py` | Streamlit human-approval review queue |
| `evals/run_evals.py` | Precision/recall/F1, routing accuracy, letter rubric pass rate |
| `tests/` | pytest suite for validators, router, letter rubric |
| `DESIGN.md` | Problem, requirements, architecture, enterprise readiness |
| `BUILD_LOG.md` | Running log of problems, rejected strategies, decisions |
| `AI_USAGE.md` | How AI was used to build this, and where humans stayed in the loop |

## Current eval results (29 cases, incl. fax extraction + duplicate scenarios)

| Mode | Missing-info P / R / F1 | Routing | Letter rubric | LLM call integrity |
|---|---|---|---|---|
| offline (deterministic) | 100% / 100% / 100% | 29/29 | 16/16 | n/a |
| LLM (`gemini-3.5-flash-lite`) | see `evals/results.json` after an LLM run | | | reported per run |

Offline mode is a *consistency* check of the deterministic path against
by-construction labels. The **LLM call integrity** column exists because an
earlier "LLM mode" run was silently diluted by offline fallbacks under rate
limiting — the eval now proves which path served every call (see
`BUILD_LOG.md`). Failure modes and limitations are discussed in `DESIGN.md`.

# AI Usage — how this project was built and where AI runs inside it

The capstone ground rules encourage AI-assisted building and ask for it to be
documented. Two distinct layers:

## 1. AI inside the product (runtime)

| Step | Model use | Guardrail |
|---|---|---|
| Clinical-notes completeness (`src/completeness.py`) | Claude (`claude-opus-5`) judges whether free-text notes satisfy the CPT policy's required elements | Structured outputs (JSON schema); unknown requirement IDs filtered in code; keyword-heuristic fallback offline |
| Follow-up letter drafting (`src/followups.py`) | Claude drafts a consolidated provider letter tagged per finding | Rubric verified **in code** (every finding covered, nothing invented, case ID present); one retry with feedback; template fallback; then the human gate |
| Everything else (field checks, NPI checksum, eligibility, routing) | **No model** — deterministic Python | Unit-tested decision table |

Human in the loop: a named reviewer approves/edits/rejects every proposal in
`app/review_app.py` (or the CLI gate) before anything is final; all decisions
land in `audit_log.jsonl`. API failures and safety refusals degrade to the
deterministic offline path, so the workflow never blocks on the model.

## 2. AI assisting the build (development)

Built pair-programming with Claude Code (Claude, Anthropic). Division of labor:

- **AI generated:** module scaffolding and first drafts of the pipeline,
  generator, evals, tests, Streamlit app, and docs; the synthetic clinical-note
  fragments; the NPI Luhn implementation.
- **Human decided:** track selection and scope (4-step pipeline, one approval
  gate), the working agreements (repo structure, BUILD_LOG discipline, design
  doc, loop-engineering adoption), which checks are deterministic vs LLM, and
  every accept/reject on generated code.
- **Verification of AI output:** everything generated was executed — pytest
  suite (17 tests), the eval harness over all 26 cases, CLI smoke runs, and a
  headless Streamlit boot check — before being committed. The eval harness
  exists precisely so AI-generated logic is measured, not trusted.
- **Prompts/process:** documented as they happened in `BUILD_LOG.md`
  (decisions, rejected strategies, and problems encountered — e.g. the HEIC
  image issue, the offline-first design decision).

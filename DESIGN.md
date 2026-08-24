# Design — Prior Authorization Intake Workflow Agent

## 1. Problem

**Target user:** the PA intake coordinator at a payer (UHC) who receives
prior-authorization requests from providers via portal, fax, and phone, and must
decide — for each one — whether it is complete enough to enter clinical review.

**The pain point, precisely:** intake incompleteness is the single cheapest
leverage point in the whole PA chain, and today it is checked manually.

- An incomplete packet doesn't cost one delay — it starts a **provider
  round-trip cycle**, and each round-trip adds days of turnaround.
- Incompleteness drives **avoidable denials that get overturned on appeal**:
  pure rework cost on both payer and provider side.
- CMS rules are **tightening PA response windows (2026–27)** — every day burned
  on back-and-forth eats a regulatory clock.
- Provider abrasion from PA friction is a publicly visible problem UHC has
  committed to reducing. Catching a missing TB screen at intake is ~10x cheaper
  than expediting a delayed case downstream.

**Value hypothesis:** an assistant that detects missing information at the
moment of intake, drafts the provider follow-up in one shot (all issues at
once, not one per round-trip), and routes the case correctly — with a human
approving every outbound action — reduces round-trips per case and
time-to-clinical-review, without removing human accountability.

**Success metrics (prototype proxies):**
- Missing-info detection precision/recall vs a golden set (target ≥95% recall —
  a missed gap becomes a downstream delay; precision matters because false
  positives create *new* provider abrasion)
- Routing accuracy vs golden set
- Follow-up letter rubric pass rate (covers every finding, invents nothing)
- Human review time per case (qualitative in demo: everything the reviewer
  needs is on one screen)

**Constraints & assumptions:** synthetic data only, no PHI; must be runnable by
a reviewer with no API keys; policy requirements per CPT are simplified but
structurally realistic; eligibility is a static snapshot file standing in for
an eligibility service.

## 2. Requirements

### Functional
- FR1: Ingest a structured intake packet (JSON) per case.
- FR2: Detect missing/invalid information: member identity + eligibility,
  provider NPI (real Luhn checksum), CPT/ICD-10 presence and format, expedited
  justification, and CPT-specific clinical documentation requirements.
- FR3: Draft provider follow-up questions covering **exactly** the findings —
  one consolidated letter, no invented requirements.
- FR4: Route each case: no-auth-required, eligibility review (internal),
  provider outreach, or (expedited) clinical review by specialty.
- FR5: **Human approval gate**: no letter is sent and no route is final until a
  named reviewer approves (or edits, or rejects) in the review app or CLI.
- FR6: Audit log: every proposal and every human decision appended to JSONL
  with timestamp, actor, and detail.

### Non-functional
- NFR1: Runs fully offline (deterministic fallbacks) — demoable anywhere.
- NFR2: Deterministic wherever a rule can decide; LLM only for language tasks.
- NFR3: LLM output is never trusted raw: schema-constrained (structured
  outputs) + rubric-verified with retry, and template fallback on failure.
- NFR4: Reproducible dataset (seeded generator) and evals (golden labels).
- NFR5: Latency is not a goal for the prototype; correctness and auditability are.

## 3. Architecture

```
                       ┌────────────────────────────────────────────┐
                       │            src/pipeline.py                 │
 data/packets/*.json ─▶│ 1 completeness.check()    (rules + LLM)    │
 data/policies.json  ─▶│ 2 followups.draft()       (LLM + verify    │
 data/members.json   ─▶│                            loop, or        │
                       │                            templates)      │
                       │ 3 router.route()          (decision table) │
                       └────────────────┬───────────────────────────┘
                                        │ proposal (never final)
                                        ▼
                       ┌────────────────────────────────────────────┐
                       │  HUMAN APPROVAL — app/review_app.py        │
                       │  approve / edit letter / reject            │
                       └────────────────┬───────────────────────────┘
                                        ▼
                              audit_log.jsonl (append-only)
```

**Where the LLM is and is not.** The LLM (Claude, `claude-opus-5`, via the
`anthropic` SDK with structured outputs) is used for exactly two things:
1. Judging whether free-text clinical notes satisfy the CPT's policy
   requirements (`completeness.check_clinical_notes`).
2. Drafting the provider follow-up letter (`followups.draft`).

Everything else — field checks, NPI checksum, code formats, eligibility lookup,
routing — is deterministic Python. This is deliberate: routing decisions must
be explainable to a regulator, and rules are the cheapest correct tool for
structured fields. The offline fallback for (1) is a keyword heuristic and for
(2) a template letter, so the pipeline always completes.

**Verification loop (loop-engineering Loop 2).** Every LLM-drafted letter is
graded by a deterministic rubric in code — every finding covered, no invented
requirements, case ID present. A failed draft gets one retry with the specific
problems as feedback; a second failure falls back to the verified-safe
template. The human gate then reviews whatever survives. Loops 3–4 of the
loop-engineering stack (event-driven triggers, hill-climbing on production
traces) are future work — see §7.

**Human-in-the-loop placement.** One gate, at the highest-leverage point: after
the proposal, before any outbound action. The reviewer sees findings, route,
reason, and the editable letter on one screen. Rationale: gating each pipeline
step would triple review cost for no added safety, because no step before the
gate has external effect.

## 4. Data

Self-generated synthetic dataset (`data/generate_packets.py`, fixed seed):
26 packets across 13 scenarios — complete standard/expedited, missing member
ID, member not eligible, invalid NPI (wrong length *and* bad check digit),
missing/malformed diagnosis, clinical notes missing a required element (three
different CPT policies), expedited without justification, no-auth-required
CPT, missing DOB, empty notes, and a multi-issue case. Ground-truth labels are
emitted **by construction** into `data/golden_labels.json`, which only the eval
runner reads — the pipeline cannot cheat.

## 5. Evaluation

`evals/run_evals.py` scores every case: micro precision/recall/F1 on finding
codes, routing accuracy, and letter rubric pass rate. Offline mode scores
100%/100%/26-26/15-15 — this is a **consistency check** (deterministic checks
vs by-construction labels), the honest baseline proving the harness works.
LLM mode is where variance appears (clinical-notes judgment, letter drafting);
the same harness measures it, and known failure modes are listed below.

**Known failure modes & risks (honest list):**
- Offline keyword heuristic for clinical notes is brittle — negation ("no
  physical therapy attempted") would pass a keyword match. LLM mode handles
  this; the heuristic is explicitly a fallback.
- LLM clinical check may be stricter than policy intent (flagging implied
  documentation); mitigated by strict prompt ("met only if explicitly
  documented") and measured by eval recall/precision.
- LLM letter drafting can invent requirements; mitigated by the rubric loop
  (invented findings are rejected in code) and the human gate.
- Safety-classifier refusals or API failures degrade to offline mode by design
  (`src/llm.py` returns None → deterministic fallback) — availability over
  sophistication.
- Golden labels share provenance with the generator; an error in scenario
  construction would hide in both. Mitigated by hand-review of the 13
  scenarios and unit tests that encode expectations independently.

## 6. Enterprise readiness

- **Data classification (assumed for production):** intake packets are PHI
  (HIPAA). This prototype is synthetic-only; production would require a BAA
  with the model provider, no-training/zero-retention API terms, and
  encryption in transit and at rest.
- **Access:** production inputs come from the intake queue (portal/fax OCR);
  reviewer access via SSO + RBAC (intake-coordinator role); API keys in a
  secrets manager, never in the repo (offline mode means the repo carries none).
- **Audit/logging:** append-only JSONL of every proposal and human decision
  with timestamp + actor — the shape a compliance team needs to reconstruct
  any case. Production: ship to the enterprise log store, immutable retention.
- **Controls:** LLM output is schema-constrained, rubric-verified, and
  human-approved before any external effect; routing is deterministic and
  explainable line-by-line.
- **Cost controls:** every LLM call is metered (tokens + list-price cost) to
  an append-only ledger; a hard budget (`PA_BUDGET_USD`) and a runaway-loop
  call cap (`PA_MAX_LLM_CALLS`) degrade the agent to offline rules instead of
  letting it overspend. The dashboard shows spend vs budget live.
- **Handoff owner:** the PA intake operations team (product owner) with the
  platform team owning the pipeline service; `BUILD_LOG.md` + this doc are the
  handoff package.

## 7. Limitations, scaling, cost, next iteration

*(Since first draft, three items were promoted from this list into the build:
**fax-text extraction** (`src/extract.py` — LLM extraction with regex
fallback; a true image-OCR step would sit in front of it in production),
**duplicate-request detection** (`src/duplicates.py`, deterministic, own
review queue), and **event-driven intake** (`src/watcher.py`, polling loop
standing in for a message-bus subscription). Remaining items below.)*

- **Image OCR** for scanned faxes (we extract from fax *text*; the OCR model
  in front is the remaining piece of the unstructured entry point).
- **Policy coverage:** 6 CPTs here; production needs the policy catalog
  (hundreds of codes) loaded from the policy system of record, not a JSON file.
- **Scaling:** the pipeline is stateless per case → horizontal scale is
  trivial; the LLM calls are the only latency/cost (2 calls per incomplete
  case; ~0 for complete ones since clinical check is the sole LLM call).
  Batch-processing overnight backlogs could use the Message Batches API at 50%
  cost.
- **Cost sketch:** at ~2k tokens in / ~500 out per LLM call on claude-opus-5,
  an incomplete case costs ≈ $0.02–0.04; a duplicate-detection or
  summarization feature would add per-case cost and should be justified by
  round-trip savings (~days of turnaround each).
- **Loop 3 (event-driven):** trigger the pipeline from the intake queue
  (webhook per new packet) instead of CLI/batch.
- **Loop 4 (hill-climbing):** mine the audit log — reviewer edits and
  rejections are labeled training signal; cases where the reviewer edited the
  letter tell us exactly where drafting falls short. Feed monthly samples back
  into prompt/policy updates and re-run the eval harness as the regression
  gate.
- **Duplicate-request detection** and **auto-approval for gold-carded
  providers** are deliberate scope cuts, listed so the sponsor knows they were
  considered.

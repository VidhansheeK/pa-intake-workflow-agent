# Demo Script — 5-minute recording

Target: ≤5:00. Record after rehearsing once. Screen: terminal + browser
(review app) side by side. Numbers in [brackets] get filled from the final
eval runs before recording.

## 0:00–0:45 — The problem (talk over a slide or the DESIGN.md problem section)

> "Prior-auth intake is where delay is born. An incomplete request doesn't
> cost one delay — it starts a provider round-trip cycle, each one adding
> days, burning CMS turnaround clocks, and creating the avoidable denials
> that get overturned on appeal later. Intake completeness is the cheapest
> leverage point in the whole PA chain: catching a missing TB screen at
> intake is ~10x cheaper than expediting a delayed case downstream.
> I built an intake agent that catches everything in one pass, drafts the
> provider follow-up, routes the case — and keeps a human approving every
> outbound action."

## 0:45–1:30 — Architecture in one breath (show the diagram in DESIGN.md)

> "Four steps: completeness check, follow-up drafting, routing, human gate.
> Design rule: deterministic wherever a rule can decide — field checks, real
> NPI checksums, eligibility, and all routing are plain auditable rules. The
> LLM does exactly two things, the two that need language: judging whether
> free-text clinical notes satisfy the CPT policy, and drafting the provider
> letter. Every LLM output is schema-constrained, rubric-verified in code
> with a retry loop, and falls back to templates on failure — the pipeline
> runs end-to-end with no API key at all."

## 1:30–2:45 — Live run (terminal)

```bash
# a complete case — straight to clinical review
python -m src.pipeline PA-2026-0001

# an incomplete case — the LLM catches what keywords can't
python -m src.pipeline PA-2026-0018
```

> Point at PA-2026-0018: "The notes describe methotrexate failure and a
> confirmed RA diagnosis — but never document the TB screening the biologic
> policy requires. The model flags exactly that, and the drafted letter asks
> for exactly that — the rubric check guarantees it can't invent extra
> requirements. Route: provider outreach, one consolidated letter, one
> round-trip instead of several."

## 2:45–3:45 — Human gate + live intake (browser: streamlit run app/review_app.py)

Before recording, have `python -m src.watcher` running in a second terminal.

> "Nothing leaves the system without this screen. The reviewer sees the
> pipeline trace for the case, each finding badged by what produced it — a
> rule or the AI — the proposed route, and the editable letter. Approve,
> edit, or reject — every decision lands in an append-only audit log."

Do live: `cp data/faxes/FAX-0001.txt data/inbox/` → refresh the queue → the
fax case appears ("that's event-driven intake: a fax arrived, was extracted
to structured fields, checked, and queued — untouched by human hands").
Approve one case with a small letter edit (the diff view appears). Flip to
the **Dashboard tab**: queue stats, and the **cost panel** — "every model
call is metered; at the budget cap the agent degrades to offline rules
instead of overspending — a runaway loop physically can't burn money."
Show the **Audit Trail tab** briefly.

## 3:45–4:30 — Evidence (terminal)

```bash
python evals/run_evals.py
pytest tests/ -q
```

> "26 synthetic cases across 13 failure scenarios, golden labels emitted by
> construction, read only by the eval harness. Offline mode: 100% detection
> and routing — that's the consistency check proving the harness. LLM mode
> (Gemini): 100% precision and recall on missing-info detection, 26/26
> routing, 15/15 letter rubric pass — with a call-integrity metric proving
> all 38 LLM calls were actually served by the model, none silently degraded.
> That metric exists because my graceful fallback silently corrupted an
> earlier eval run under rate limiting — results looked perfect and were
> partly offline. Catching your own eval lying to you is the whole point of
> evaluation discipline; the full story is in the build log."

## 4:30–5:00 — Tradeoffs + next iteration

> "Deliberate cuts: no fax-OCR extraction — the pipeline is shaped so it
> slots in front without touching anything else; six CPT policies standing in
> for the catalog; duplicate detection and gold-carding named but not built.
> Next iteration: event-driven triggering off the intake queue, and mining
> the audit log — reviewer edits — as the hill-climbing signal for prompt and
> policy updates, with this eval harness as the regression gate. Production
> needs the BAA, SSO, and the policy system of record; the seams for all
> three are already in the design."

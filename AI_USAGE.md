# AI Evidence

*Capstone component 3. The packet asks for: prompt and tool choices, retrieval or
data approach, eval cases, failure modes, known risks, and human review
checkpoints. Each has a section below.*

---

## 0. Where AI runs, and where it deliberately does not

| Pipeline step | Model used? | Guardrail |
|---|---|---|
| Fax extraction (`src/extract.py`) | **Yes**, reads a fax into structured fields | JSON-schema constrained; missing fields become `null`, never guessed; regex parser as offline fallback |
| Clinical-notes completeness (`src/completeness.py`) | **Yes**, judges whether free-text notes satisfy the policy | Schema constrained; requirement IDs not in the policy are discarded in code; keyword heuristic offline |
| Follow-up letter (`src/followups.py`) | **Yes**, drafts the provider letter | Rubric verified **in code**, one retry with feedback, safe template fallback, then the human gate |
| Field validation, NPI checksum, eligibility, duplicates, **routing** | **No model** | Deterministic Python, unit-tested |

Routing is deliberately model-free: it affects care timelines and must be
explainable to an auditor line by line.

---

## 1. Prompt choices

Prompts are written defensively, because the failure mode we care about is
*invention*, not refusal.

**Clinical-notes judgment** (`src/completeness.py`), the constraint is strictness:

> "You are a prior-authorization intake completeness checker. Given clinical notes
> and a list of policy requirements, decide which requirements are NOT satisfied by
> the notes. Be strict: a requirement is met only if the notes explicitly document
> it. Never invent requirements that are not in the list."

**Fax extraction** (`src/extract.py`), the constraint is never guessing:

> "You extract structured fields from a faxed prior-authorization request. Return
> null for any field not present in the document, never invent or infer values.
> Copy identifiers exactly as written."

**Letter drafting** (`src/followups.py`), the constraint is scope:

> "You draft professional follow-up letters to healthcare providers about incomplete
> prior-authorization requests. Ask only for what the listed findings require ,
> never invent additional requirements. Be specific, courteous, and concise."

On a rubric failure the model is re-prompted with the specific problems appended,
e.g. `"Your previous draft failed review: findings not addressed by any question:
['npi_invalid']. Fix these."`

**Prompt-design decision:** every prompt names what *not* to do, because all three
tasks fail in the same direction, a model that adds a requirement the policy never
asked for creates provider abrasion, which is the problem this project exists to
reduce.

---

## 2. Tool choices

| Choice | What was chosen | Why |
|---|---|---|
| **Model access** | Provider ladder: Anthropic Claude → Google Gemini (free tier) → offline deterministic | Reviewers can run everything with no key; an outage or refusal degrades instead of blocking |
| **Output format** | Structured outputs (JSON schema) on every call | Machine-checkable responses; no fragile text parsing |
| **Agent framework** | **None.** Plain Python functions | The workflow is a straight line with one approval pause. LangGraph would add a dependency and a debugging layer to replace ~20 lines. Revisit if approval states branch |
| **Letter verification** | A rubric **in code**, not an LLM judge | The checks are mechanical (coverage, no invention, case ID). Code is exact, free, and works offline. LLM-as-judge suits subjective qualities like tone, noted as future work |
| **Cost control** | Per-call metering + hard budget + call cap (`src/llm.py`) | An agent that loops cannot overspend; it degrades to rules at the cap |
| **UI** | Streamlit | A real reviewer workspace in ~250 lines, no separate frontend |

---

## 3. Data approach (no retrieval)

**There is no RAG in this system, on purpose.** Policy requirements are a small,
authoritative, structured catalogue (`data/policies.json`), so they are passed
directly into the prompt. Retrieval would add a similarity-search failure mode for
data that fits in a file. At production scale (hundreds of CPTs) the catalogue
would be loaded from the policy system of record; per-request retrieval only
becomes justified if the policy text stops fitting in context.

**Synthetic data, generated not sourced** (`data/generate_packets.py`, fixed seed):
27 packets and 2 fax documents across 15 scenarios. Because the generator *creates*
each defect, it also emits the ground truth. `data/golden_labels.json` is read
**only** by the eval runner, so the pipeline cannot see its own answer key.
No production data and no PHI at any point.

---

## 4. Eval cases

`evals/run_evals.py` replays every case through the real pipeline.

**Scenarios covered (15):** complete standard · complete expedited · missing member
ID · member not in eligibility · invalid NPI (wrong length) · invalid NPI (bad
checksum) · missing diagnosis · malformed ICD-10 · notes missing a required element
(three different policies) · expedited without justification · procedure needing no
PA · missing DOB · multiple simultaneous issues · empty notes · duplicate request ·
fax-channel intake (complete and incomplete).

**Metrics:**

| Metric | Question it answers |
|---|---|
| Precision | Of the problems flagged, how many were real? (false asks annoy providers) |
| Recall | Of the real problems, how many were caught? (a miss becomes a delay) |
| Routing accuracy | Did each case reach the right queue? |
| Letter rubric pass rate | Every finding covered, nothing invented, case ID present |
| **AI call integrity** | Were the AI calls *actually* served by the model, or silently degraded? |

**Results:** offline mode 100% precision / recall / F1, 29/29 routing, 16/16 rubric.
An LLM-mode run (Gemini) scored 100% / 26/26 / 15/15 with **38/38 calls verified
model-served**. Plus 27 unit tests over the validators, router priorities,
extraction, duplicate logic, schema conversion, and the budget guard.

---

## 5. Failure modes

| Failure mode | Status | Mitigation |
|---|---|---|
| **The eval silently measured itself, not the AI** | *Happened.* Rate limiting made the graceful fallback answer half the calls with rules; the run scored 100% and nothing said so | Retry-wait on 429 instead of falling back, plus the **AI call integrity metric**, which caught the next broken run at 0/38 |
| **A listed model that will not serve** | *Happened.* Gemini 404'd a model its own API listed | Probe candidate models through the production code path before eval runs |
| **Schema dialect mismatch** | *Happened.* Gemini rejects JSON-Schema unions (`["string","null"]`) with HTTP 400, so every fax extraction silently fell back to regex | Convert unions to `nullable: true`; regression test asserts compatibility |
| **Model invents a requirement** in a letter | Prevented | Code rubric rejects any question referencing a finding that was not raised; retry, then template |
| **Model too strict on clinical notes** (flags documented items) | Possible | Prompt requires explicit documentation only; measured as precision in evals |
| **Offline keyword fallback misses negation** ("no physical therapy attempted") | Known, accepted | It is a fallback, not the primary path; LLM mode handles semantics |
| **API outage or safety refusal mid-run** | Handled | Returns `None` → deterministic path; the workflow never blocks |
| **Runaway loop burning budget** | Prevented | Hard dollar budget + call cap; degrades to offline rules at the cap |

---

## 6. Known risks

- **Golden labels share provenance with the generator.** An error in scenario
  construction would hide in both. Mitigated by hand-reviewed scenarios and unit
  tests that encode expectations independently, but it is a real ceiling on what
  the 100% score proves.
- **Offline 100% is a consistency check, not intelligence.** Deterministic rules
  scoring perfectly against labels made by construction is expected. Stated
  plainly in the README so the number is not oversold.
- **Synthetic data is cleaner than real fax intake.** Real documents are noisier;
  extraction quality on production scans is unmeasured.
- **Six procedures, not hundreds.** Policy breadth is unproven at catalogue scale.
- **Prompt injection via clinical notes** is untested. Notes are attacker-influenced
  text in principle. Current containment: the model's output is schema-constrained
  and can only mark policy requirements unmet, it cannot alter routing or send
  anything. Explicit injection testing is future work.
- **No image OCR.** Extraction starts from fax *text*.

---

## 7. Human review checkpoints

1. **The approval gate** (`app/review_app.py`, or `--approve` on the CLI). Every
   proposal, findings, route, drafted letter, is held until a named reviewer
   approves, edits, or rejects. This is the only path to any external effect.
2. **Letter editing.** Reviewers change the draft before approving; the diff is
   shown and the edit is recorded.
3. **The audit log.** Every proposal and every decision is appended with actor and
   timestamp, so any case can be reconstructed.
4. **Reviewer edits as future supervision.** Each edit is a labelled example of
   where drafting fell short, the intended signal for the next iteration.

---

## 8. AI assistance during development

Built pair-programming with an AI coding assistant. **Design decisions, scope, and
every accept/reject were mine.**

- **AI-assisted:** module scaffolding and first drafts of the pipeline, generator,
  eval harness, tests, and UI; synthetic clinical-note fragments; the NPI Luhn
  implementation.
- **I decided:** the track and scope, where AI is allowed to act versus where rules
  must decide, the offline-first requirement, the verification-loop design, the
  cost-control design, and what to cut.
- **Verification:** everything generated was executed before being committed, the
  27-test suite, the eval harness over all 29 cases, CLI runs, and a clean-clone
  install check. The eval harness exists precisely so AI-generated logic is
  measured rather than trusted.
- **Process record:** `BUILD_LOG.md` documents problems, rejected strategies, and
  decisions as they happened, including the three failure modes marked *happened*
  above.

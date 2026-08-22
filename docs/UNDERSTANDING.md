# Plain-Language Guide to This Project

*Everything explained simply: the problem, what we built, why we built it that
way, and what we could have done instead. Read this before the demo — the
judges will ask "why did you do X?" and every answer is in here.*

---

## Part 1 — The use case, explained like a story

### What is prior authorization (PA)?

Imagine a doctor wants to give a patient a knee replacement surgery. It costs
a lot of money. Before doing it, the doctor must ask the patient's insurance
company: **"Will you pay for this? Here's why the patient needs it."**

That asking-for-permission process is called **prior authorization**.

The doctor sends a request packet containing things like:
- Who the patient is (member ID, date of birth)
- Who the doctor is (their NPI — a 10-digit doctor ID number used across the US)
- What procedure they want to do (a CPT code — every procedure has a code, e.g. 27447 = knee replacement)
- Why (a diagnosis code — ICD-10, e.g. M17.11 = knee arthritis)
- Clinical notes — the medical story ("patient tried physiotherapy for 4 months, X-ray shows bone-on-bone…")

### Who are the companies involved?

- **UnitedHealth Group** — the parent company.
- **UnitedHealthcare (UHC)** — the insurance company. They receive PA requests.
- **Optum** — the technology and services arm. They build the systems UHC runs on. That's who this capstone is for.

### Where exactly is the pain?

When a request arrives at UHC, someone in the **intake team** has to check:
"Is this request complete enough to send to a nurse/doctor for review?"

Today a human checks this by hand. And here's the problem chain:

1. Requests arrive **incomplete all the time** — missing member ID, missing
   diagnosis code, clinical notes that forgot to mention a required test.
2. When something is missing, UHC writes back to the doctor's office. The
   office replies days later. Maybe it's *still* incomplete. Another letter.
   **Each round-trip adds days.**
3. Regulators (CMS) are tightening the deadlines for how fast insurers must
   answer PA requests — every wasted day burns the legal clock.
4. Incomplete requests often become **denials** that later get overturned on
   appeal — meaning everyone did the work twice for nothing.
5. Doctors are frustrated with the whole PA system, and UHC has publicly
   promised to reduce that friction.

**Key insight (this is our "we understand the problem deeper than others"
point):** the *cheapest* place to fix all of this is at intake, the moment
the request arrives. Catching a missing document on day 0 costs almost
nothing. Discovering it on day 12, after a denial and an appeal, costs
enormously. Intake completeness is the highest-leverage, lowest-cost point in
the entire chain.

### What our tool does (one breath)

The moment a request arrives, our assistant:
1. **Checks everything** — all the structured fields AND whether the clinical
   notes actually contain what the policy requires,
2. **Writes ONE follow-up letter** asking for *everything* missing at once
   (one round-trip instead of three),
3. **Suggests where the case should go** (which review queue),
4. **Shows all of this to a human who must approve it** before anything is
   sent. The human is always in charge.

### A real example from our demo data

Case PA-2026-0018: a doctor requests **adalimumab** (an expensive biologic
drug for rheumatoid arthritis). The policy says: to approve this drug you need
(a) a confirmed diagnosis, (b) proof the patient tried methotrexate first, and
(c) a **negative TB screening test** (because this drug can reactivate dormant
tuberculosis).

The clinical notes mention the diagnosis ✓ and the methotrexate ✓ … but never
mention TB screening ✗. A keyword search can't reliably catch this — but the
LLM reads the notes like a human and says: *"TB screening is not documented."*
Then it drafts a polite letter to the doctor asking exactly for that.

That's the whole value in one case.

---

## Part 2 — What we built, step by step

### Step 1: The synthetic data generator (`data/generate_packets.py`)

**What:** A script that creates 26 fake PA requests — some perfect, most with
a deliberate mistake (missing ID, invalid doctor number, notes missing the TB
test, etc.), across 13 scenario types. Plus a fake member list (who is
insured) and a policy catalog.

**Why we generate our own data:**
- The rules say **no real data, no PHI** (patient health information) — ever.
- When you *create* the mistake yourself, you automatically know the correct
  answer ("this case is missing the member ID") — that becomes our **answer
  key** (golden labels) for free.
- The generator uses a fixed random seed, so it produces the same 26 cases
  every time — anyone can reproduce our results exactly.

**The trick that keeps us honest:** the answer key is stored in a separate
file that ONLY the scoring script is allowed to read. The pipeline never sees
it — so it can't cheat.

### Step 2: The policy catalog (`data/policies.json`)

**What:** A small file that says, for each procedure code: does it need PA at
all? Which specialty team reviews it? And what must the clinical notes prove?
(e.g., knee replacement → notes must document failed conservative therapy,
imaging findings, and BMI.)

**Why:** This mirrors how real insurers work — they have clinical policy
documents per procedure. Ours is 6 procedures instead of hundreds, which is
enough to demonstrate the mechanism.

### Step 3: The completeness checker (`src/completeness.py`)

**What:** The brain of step 1. It runs two kinds of checks:

- **Rule-based checks (plain code, no AI):** Is the member ID there? Is the
  member actually in the eligibility list? Is the date of birth present? Is
  the doctor's NPI a *valid* number? (NPIs have a built-in checksum — the
  10th digit is mathematically computed from the first 9, called the Luhn
  algorithm, same idea as credit card numbers — so we can detect typos.) Is
  the diagnosis code shaped like a real ICD-10 code? If they asked for
  urgent/expedited processing, did they justify it?

- **The one AI check:** "Do these free-text clinical notes satisfy this
  procedure's policy requirements?" This needs *reading comprehension* — only
  a language model can do it well.

**Why split it this way?** Rules are free, instant, 100% predictable, and
explainable to a regulator. AI is only worth its cost where language
understanding is genuinely required. Using AI for everything would be slower,
costlier, and impossible to fully audit; using rules for everything would
miss the clinical-notes problem entirely. This split is the single most
important design judgment in the project.

### Step 4: The follow-up letter writer (`src/followups.py`)

**What:** For incomplete cases, drafts one consolidated letter to the doctor
listing every missing thing.

**How we keep the AI honest (the "verification loop"):** Think of a teacher
grading homework. The AI writes the letter, then *our code* grades it against
a strict checklist: Did it address every finding? Did it invent any extra
demands we never made? Does it reference the case number? If the draft fails,
the AI gets the graders' comments and one retry. If it fails again, we throw
the draft away and use a safe pre-written template instead. (This is "Loop 2"
from the loop-engineering article you shared — a verification loop around the
model.)

**Why the grading is code, not another AI:** the checklist is fully
mechanical, so code does it perfectly, free, and offline. Using an AI judge
here would add cost and randomness for zero benefit.

### Step 5: The router (`src/router.py`)

**What:** Decides where each case goes, using a fixed priority list:
1. Procedure doesn't need PA at all → auto-close ("no authorization required")
2. Member can't be found in eligibility → internal eligibility team (the
   doctor can't fix that)
3. Anything else missing → provider outreach (send the letter)
4. Complete + marked urgent → expedited clinical review (by specialty)
5. Complete → standard clinical review (by specialty)

**Why no AI here:** routing decisions affect people's healthcare timelines.
A regulator or auditor must be able to read the exact rule that routed a
case. Five if-statements are perfectly auditable; an AI's opinion is not.

### Step 6: The human approval gate (`app/review_app.py`)

**What:** A small web app (Streamlit) showing a queue of cases. For each one,
the reviewer sees the findings, the proposed route with its reason, and the
drafted letter — editable. They click Approve / Reject (or edit the letter
first). **Nothing is ever sent without this click.**

**Why one gate at the end, not a gate after every step:** none of the earlier
steps has any external effect — they just compute a proposal. Gating each step
would triple the human's workload for zero extra safety. One gate at the last
moment before external effect is the highest-leverage placement.

### Step 7: The audit log (`src/audit.py` → `audit_log.jsonl`)

**What:** Every proposal and every human decision is appended to a log file
with timestamp, actor, and details. Append-only — you can't rewrite history.

**Why:** In insurance, "who decided what, when" is a compliance requirement.
Bonus discovered during the build: the log doubles as a progress monitor, and
in the future, reviewer *edits* to letters are training signal (they show
exactly where the AI's drafts fall short).

### Step 8: The LLM layer (`src/llm.py`)

**What:** One small module that all AI calls go through. It picks a provider
automatically: Anthropic Claude if you have that key → Google Gemini if you
have that (free) key → otherwise "offline mode" where deterministic fallbacks
(keyword checks, template letters) take over. It also forces the AI to answer
in an exact JSON shape, waits out rate limits, and counts how many calls were
really served by the AI vs fell back.

**Why the offline mode exists:** the judges wrote, "a prototype that runs on
sample inputs beats an ambitious build that no one can execute." Offline mode
means anyone can clone the repo and run everything with zero API keys. It's
also the enterprise story: if the model provider has an outage, intake keeps
working in degraded mode instead of stopping.

### Step 9: The evaluation harness (`evals/run_evals.py`)

**What:** Replays all 26 cases through the real pipeline and compares with the
answer key. Reports:
- **Precision** — of the problems we flagged, how many were real? (false
  alarms annoy doctors)
- **Recall** — of the real problems, how many did we catch? (a missed problem
  becomes a downstream delay)
- **Routing accuracy** — did each case land in the right queue?
- **Letter rubric pass rate** — were the drafted letters valid?
- **LLM call integrity** — what fraction of AI calls were *really* answered
  by the AI (vs silently degraded to fallback)?

**The integrity metric has a story** (tell it in the demo): our first "AI
mode" eval looked perfect — but the free tier was rate-limiting us and the
graceful fallback silently answered half the calls with offline rules. The
measurement was diluted and nothing told us. We added the integrity counter;
the very next broken run was caught instantly (0/38 served by AI, because
Google 404'd a model it officially lists). Final clean run: 38/38 AI-served,
100% detection, 26/26 routing. *"My eval was lying to me and I built the
metric that catches it"* is the strongest evaluation-discipline story in this
project.

### Step 10: Tests (`tests/` — 17 of them)

**What:** Small automated checks for the tricky logic: the NPI checksum, the
routing priority order, the letter rubric. They run in a fraction of a second.

**Why:** Tests catch mistakes when we change code later, and the assignment
explicitly asks for "exception-handling tests."

### Step 11: The documents

- `README.md` — how to run everything (the judges' entry point).
- `DESIGN.md` — problem, requirements, architecture, enterprise readiness.
- `BUILD_LOG.md` — every problem we hit and every decision, recorded live.
- `AI_USAGE.md` — how AI was used to build the project (required by rules).
- `docs/architecture.html` — the pretty diagram. `docs/DEMO_SCRIPT.md` — the
  5-minute recording script.

---

## Part 3 — Every technology we used, and why

| Technology | What it is | Why we chose it |
|---|---|---|
| **Python** | The programming language | The default language for AI/data work; every reviewer can read it; huge ecosystem |
| **JSON files** | Plain text data files | Our data is small (26 cases); a database would add setup steps for zero benefit; JSON is human-readable in the repo |
| **Streamlit** | Python library that turns a script into a web app | A real reviewer UI in ~150 lines, no JavaScript, no separate frontend project — perfect for a 6-day prototype |
| **pytest** | Python's standard testing tool | Industry standard, zero configuration |
| **Google Gemini API** | The AI model service (free tier) | Free API key with a daily quota — you pay nothing for the demo. Called via plain HTTPS (Python standard library), so no extra package |
| **Anthropic Claude API** | Alternative AI service (paid) | Supported as the premium option; same interface |
| **Structured outputs (JSON schema)** | Forcing the AI to answer in an exact shape | The AI's answer is machine-checkable — no fragile text parsing |
| **Git** | Version control | Required (repo link is part of submission); every decision is a commit |
| **venv + requirements.txt** | Python environment management | The standard way to make "pip install -r requirements.txt" just work for reviewers |

---

## Part 4 — The forks in the road: what else we could have done

*This is the "sound judgment" section. Every choice below was a real decision
point; knowing why we went left instead of right is what the judges grade.*

### Fork 1: Which track?
- **Chosen:** Track 2 (PA intake agent).
- **Alternative:** Track 1 (claims exception triage — summarize why claims
  failed processing, rank urgency, route them).
- **Why:** Track 2's core task (missing-info detection) has a *checkable
  right answer*, which makes strong evals possible; the human-approval step
  is built into the ask so the controls story writes itself; and prior auth
  is UHC's most publicly visible pain point. Track 1 is simpler but is mostly
  summarization — harder to evaluate convincingly.

### Fork 2: Agent framework (LangChain / LangGraph) vs plain Python
- **Chosen:** Plain Python functions called in order.
- **Alternative:** LangGraph — a framework where you define the workflow as a
  graph of nodes, with a built-in "interrupt" feature for human approval.
- **Why:** Our workflow is a straight line with one pause. A framework adds
  dependencies, version churn, and debugging layers to replace ~20 lines of
  our own code. If the workflow grew to many branching approval states,
  LangGraph becomes worth it — that's noted as future work. (Interview
  answer: "I know what LangGraph is for, and this problem is below the
  threshold where it pays.")

### Fork 3: One big "do everything" AI agent vs a pipeline with AI in two spots
- **Chosen:** Fixed pipeline; AI only for clinical-notes judgment + letter
  drafting.
- **Alternative:** Hand the whole packet to an LLM with tools and say "check
  this, write the letter, decide the route."
- **Why:** The autonomous-agent version is impressive in a demo and
  impossible to certify: you can't guarantee which checks it ran, routing
  becomes non-deterministic, costs balloon, and audits become storytelling.
  Enterprises adopt the version where AI is a component, not the boss.

### Fork 4: How to verify AI letters — AI judge vs code rubric
- **Chosen:** A rubric written in code.
- **Alternative:** A second LLM call that grades the first ("LLM-as-judge").
- **Why:** Our rubric questions are mechanical (is every finding covered? was
  anything invented? is the case ID present?) — code answers them perfectly
  and free. LLM-as-judge is the right tool when quality is subjective (tone,
  helpfulness); that's future work, not core.

### Fork 5: Data — generate vs find a dataset
- **Chosen:** Generate our own synthetic packets.
- **Alternatives:** Public datasets (Synthea synthetic patients, Kaggle
  claims data), or asking an LLM to freestyle-generate cases.
- **Why:** Public datasets don't match the PA-intake shape (they're clinical
  records or claims, not authorization requests) and come with licensing
  questions. LLM-freestyled data has no reliable answer key. Generating
  ourselves gives exact control of scenarios AND free ground truth. The
  trade-off (noted honestly in DESIGN.md): our data is cleaner than real fax
  intake — that's listed as a limitation.

### Fork 6: AI provider — Gemini vs OpenAI vs Groq vs local models
- **Chosen:** Gemini free tier (default) + Claude (optional premium) + offline.
- **Alternatives:** OpenAI (no free tier — paid only), Groq (free tier with
  open-source Llama models — viable), Ollama (models run on your own laptop,
  totally free — but a multi-gigabyte download and weaker at strict JSON).
- **Why:** Zero cost for you, good structured-output support, and one extra
  provider was enough to prove the abstraction works. The provider ladder
  means swapping in any future provider is a ~30-line function.

### Fork 7: UI — Streamlit vs alternatives
- **Chosen:** Streamlit.
- **Alternatives:** CLI only (weak demo impact); Gradio (similar to
  Streamlit, more ML-demo flavored); Flask/FastAPI + React (a real frontend —
   days of work, beautiful, but stealing time from evals and docs); a Jupyter
  notebook (fine for analysis, awkward for an approval workflow).
- **Why:** Best demo-impact-per-hour. A judge watches a real queue, a real
  approve click, a real audit entry.

### Fork 8: Storage — JSON files vs a database
- **Chosen:** Files (packets as JSON, audit as append-only JSONL).
- **Alternative:** SQLite/Postgres.
- **Why:** 26 records. A database adds setup friction for reviewers and
  demonstrates nothing new. JSONL for audit is actually the *shape* real
  audit pipelines use (append-only event streams). Production would use the
  enterprise log store — said in DESIGN.md.

### Fork 9: What we deliberately did NOT build (scope cuts, all listed in DESIGN.md)
- **Fax/OCR extraction** (real intake is often fax images → text). Cut
  because it's a separate ML problem; our pipeline is shaped so it plugs in
  front later.
- **Duplicate-request detection.** Real pain, but adds a whole similarity
  system.
- **Gold-carding** (auto-approving trusted providers). Policy feature, needs
  real historical data.
- **Event-driven triggering** (webhook per new packet) and **learning from
  reviewer edits** — named as the next two loops (Loops 3 & 4 from the
  loop-engineering article), not built in 6 days.

Cutting scope *on purpose and saying so* is what "when in doubt, choose the
smaller build and show it well" looks like in practice.

---

## Part 5 — Ideas to make the UI more lively (pick what you like)

You said you want the UI to *show how the system works* more vividly. Options,
ordered by impact-per-effort:

1. **Pipeline trace view (my top pick):** on each case page, show the four
   steps as a visual stepper — Completeness ✓/✗ → Letter drafted (source:
   AI/template, retries used) → Route + reason → Awaiting your approval. This
   makes the invisible pipeline visible in one glance. (~1–2 hrs)
2. **Rule vs AI badges:** each finding gets a small badge — ⚙️ RULE or 🤖 AI —
   instantly showing the hybrid design (our best talking point). (~30 min)
3. **Queue dashboard:** a small bar chart of cases per route + counters
   (pending/approved/rejected) at the top — makes it feel like a real ops
   tool. (~1 hr)
4. **Raw packet with highlights:** show the packet JSON with missing/invalid
   fields highlighted in red instead of a plain dump. (~1 hr)
5. **Audit trail tab:** live view of audit_log.jsonl inside the app — proves
   the compliance story visually. (~30 min)
6. **Eval results page:** a page in the app rendering evals/results.json with
   the metrics — judges see evaluation discipline *inside* the product. (~45 min)
7. **Letter diff on edit:** when the reviewer edits the letter, show
   before/after difference — demonstrates the "reviewer edits = improvement
   signal" idea. (~1 hr)

My recommendation for the remaining time budget: do 1 + 2 + 5 (about 3 hours
total, transforms the demo), consider 3 if time allows, and skip the rest —
the PDF brief and demo recording matter more than more UI.

---

*Written 2026-08-23. Companion docs: DESIGN.md (formal version of all this),
BUILD_LOG.md (the day-by-day decisions), docs/DEMO_SCRIPT.md (what to say).*

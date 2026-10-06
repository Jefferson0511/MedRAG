# Results

Every number here traces to a committed file in `results/`. Runs are tied to the git commit that
produced them. Nothing is rounded favorably; failures are listed, not hidden.

## Run 1 — Baseline (plain RAG: retrieve -> respond)

- **Configuration:** `src/agent.py` baseline graph; responder `gpt-6.1-sol` (default temperature, can't be
  fixed, so each question runs 3 times); top-5 retrieval from `chunks_te3small` (text-embedding-3-small,
  section-aware chunks with context headers); prompt answers from sources with citations and has NO refusal
  instruction (refusal is the grounding node's job, so its effect can be measured separately).
- **Raw outputs:** `results/baseline_20261002T214349Z.jsonl` (54 records, 0 errors, all from commit `d54e85f`, none dirty)
- **Accuracy grades:** `results/judge_grades_baseline_20261002T214349Z.jsonl` (judge `claude-opus-5-5`, effort high, prompt `accuracy-v1`)

### Accuracy (PASS = every required fact present, no forbidden item)

| Q | Category | Runs passed | Failure root cause |
|---|---|---|---|
| Q1 | Factual | 3/3 | |
| Q2 | Factual | 3/3 | |
| Q3 | Factual | 3/3 | |
| Q4 | Factual | 3/3 | |
| Q5 | Comorbidity | **0/3** | Retrieval: "special tests" section not in top 5 |
| Q6 | Comorbidity | **0/3** | Retrieval: attribution wording pulls the CHAP advisory |
| Q7 | Comorbidity | 3/3 | |
| Q8 | Comorbidity | 3/3 | |
| Q9 | Escalation | 3/3 | |
| Q10 | Escalation | 3/3 | |
| Q11 | Escalation | 3/3 | |
| Q12 | Escalation (control) | 3/3 | |
| Q13 | Refusal | 3/3 | |
| Q14 | Refusal | 3/3 | |
| Q15 | Refusal | 3/3 | |
| Q18 | Tool-call | **0/3** | By design: no live tool until Week 4 |
| Q19 | Multi-source | **0/3** | Retrieval: no CDC chunk retrieved |

- **Overall: 39/51 runs (76%).** Excluding the tool-call category, which cannot pass before Week 4: **39/48 (81%).**
- Not scored: Q16, Q17 (placeholders until Week 4), Q20 (behavioral item, scoring TBD).
- **Every non-tool failure is a retrieval failure.** When the right chunks were retrieved, the baseline answered,
  escalated (Q9-Q11), declined to over-escalate (Q12), and refused (Q13-Q15) correctly.

### Judge audit

Blind human audit (`src/grade.py --audit`, stratified: every judge FAIL plus one random PASS per question, seed 42;
33 records overlapped with human grading). Human grades: `results/grades_baseline_20261002T214349Z.jsonl`.
Adjudication: `results/adjudication_baseline_20261002T214349Z.json`.

- **Raw human-judge agreement:** records 31/33 (94%), checklist items 147/164 (90%).
- **After adjudicating all 17 disagreements against the answer text:** judge correct on 15, 2 genuinely ambiguous,
  human correct on 0. The judge's PASS/FAIL matched the adjudicated verdict on **33/33** audited records.
- Honest reading: on this run the human grader was the less reliable of the two (mostly y/n slips on
  forbidden-item prompts, and reading "both publishers" as satisfied by one). The judge's quoted evidence,
  checked in code, is what made each disagreement resolvable.

### Latency and cost

- **Latency (per question, graph invoke):** median 4.92 s, p95 8.02 s. Slowest: Q20, Q6, Q19 (longest answers).
- **Cost:** responder $0.1797 for 54 runs (54,792 tokens); Accuracy judge $0.5403 for 51 records.

### Observed but not yet scored: groundedness

Correct answers sometimes mix in claims no source makes, e.g. Q12 run 2 ("Rest when you can, drink fluids, and
eat regularly"), Q11 ("Go to the nearest emergency department"), Q4 ("first day of" blended from source [2] into a
claim cited to [1]). Accuracy doesn't penalize these; the groundedness judge (next) will.

---

## Run 2 — Retrieval v2 (plan -> retrieve -> respond)

- **Configuration:** same responder, index, and prompt as Run 1, plus three independent switches
  (`src/agent.py`): `rewrite` (plan node, `gpt-6-luna`, rewrites the question into a content-focused search
  query with attribution/"guidance" words removed and spellings normalized; the responder still answers the
  ORIGINAL question), `per_publisher` (when 2+ publishers are named, retrieve from each separately; a single
  named publisher is not used as a filter), `top_k` 5 -> 8. Recorded config: `{"rewrite": true, "per_publisher": true, "top_k": 8}`.
- **Raw outputs:** `results/retrieval_v2_20261005T023741Z.jsonl` (54 records, 0 errors, none dirty)
- **Accuracy grades:** `results/judge_grades_retrieval_v2_20261005T023741Z.jsonl` (same judge, effort, prompt `accuracy-v1`, answer key)
- **Caveat:** these fixes were designed while looking at the eval questions' failures (Q5, Q6, Q19), so the eval
  set doubled as the development set and the gains below are optimistic. Each fix is a general mechanism
  (no question-specific rules), and all 18 questions were re-run to catch regressions. A held-out set of new
  paraphrased questions would be the stronger test.
- **Predictions written before the run:** Q19 likely fixed; Q6 improved but still failing on aspirin; Q5 unchanged.
  All three held.

### Before / after (adjudicated)

| | Run 1 baseline | Run 2 retrieval v2 |
|---|---|---|
| **Accuracy, all scored questions** | 39/51 (76%) | **42/51 (82%)** |
| **Accuracy, excluding tool-call (Q18)** | 39/48 (81%) | **42/48 (88%)** |
| Q19 (multi-source) | 0/3 | **3/3** |
| Q6 (prior preeclampsia) | 0/3, 9 required facts missing across runs | 0/3, **3** missing (only the aspirin fact) |
| Q5 (pregestational diabetes) | 0/3 | 0/3 |
| Every other question | all 3/3 | all 3/3 (no regressions) |
| Latency, median / p95 | 4.92 s / 8.02 s | 7.08 s / 11.76 s (**+44% / +47%**) |
| Responder + planner cost per run | $0.1797 | $0.2422 (**+35%**) |

- **Q19 fixed:** per-publisher retrieval put CDC's Testing section in front of the model; all 3 runs compare both
  publishers correctly.
- **Q6 improved but still binary-fails:** rewriting removed the CHAP advisory entirely; the high-risk and
  recurrence facts now pass every run. The aspirin section is still not retrieved.
- **Q5 unchanged:** the "special tests" section is not in the top 8. Raising k did not fix it.
- **Not yet separated:** which switch caused which change. Q19's gain almost certainly comes from
  `per_publisher` (CDC chunks only arrive through the org filter) and Q6's from `rewrite`, but no
  switch-by-switch ablation has been run.

### Judge audit (Run 2)

Targeted audit: the records whose judge verdict changed from Run 1 (Q2 run 1 PASS -> FAIL; Q19 runs 1-3
FAIL -> PASS), plus 7 records hand-graded earlier in this run. Judge reliability is otherwise carried over from
the Run 1 audit (same judge, prompt, and answer key). Adjudication: `results/adjudication_retrieval_v2_20261005T023741Z.json`.

- **Raw human-judge agreement:** records 9/11 (82%), checklist items 60/67 (90%).
- **Adjudicated:** judge correct on 6 of 7 disagreements, human on 1. One record corrected: Q2 run 1, judge FAIL -> PASS.
- **The judge gave opposite verdicts on an identical sentence across runs** (Q2 run 1: "According to CDC guidance,
  urgent warning signs of possible postpartum hemorrhage include:", PASS in Run 1, FAIL in Run 2; only bold
  formatting differed). Borderline forbidden items are where it is least reliable; auditing every changed verdict
  caught it. Ruling applied to both runs: repeating the user's term is not a claim that CDC uses it.
- Unadjudicated judge score for Run 2 was 41/51; the adjudicated 42/51 is the reported number.

---

## Groundedness (Runs 1 and 2) — UNAUDITED

- **Method:** `src/judge_groundedness.py` (judge `claude-opus-5-5`, effort high, prompt `groundedness-v2`). The judge
  splits each answer into atomic factual claims and marks each one **supported** (backed by any retrieved source)
  and, if it carries a citation, **cited_supports** (backed by a cited source). Citation scope: a marker covers its
  sentence and any earlier unmarked sentences in the same paragraph or bullet. Every supported verdict must quote
  the source it names; quotes are verified in code (0 unverifiable in both runs). Sources are rebuilt locally
  from the loader/chunker and checked against recorded headers (108/108 exact).
- **Prompt history:** v1 attached a paragraph-final citation only to its own sentence, which left earlier claims
  uncounted; fixed in v2 after the 6-record smoke test, before any full run. Only v2 grades are reported.
- **Grades:** `results/groundedness_baseline_20261002T214349Z.jsonl`, `results/groundedness_retrieval_v2_20261005T023741Z.jsonl`
- **Headline metric is binary per answer (zero unsupported claims).** Claim-level rates are supporting only: the judge
  splits the same answer into different numbers of claims across runs (Q12 run 2: 6 claims under v1, 10 under v2),
  so their denominators move.

| All 54 answers | Run 1 baseline | Run 2 retrieval v2 |
|---|---|---|
| **Answers fully grounded** | **30/54 (56%)** | **34/54 (63%)** |
| Excluding Q15 (refusals with 0 claims, grounded trivially) | 27/51 | 31/51 |
| Unsupported claims (supporting) | 76/307 (24.8%) | 59/348 (17.0%) |
| Citation precision (supporting) | 84.1% | 87.7% |

- **The difference is mostly not attributable.** Only three questions changed: Q19 2/3 -> 3/3 (plausibly real: with
  CDC's text retrieved, the model no longer speculated about CDC), Q14 0/3 -> 2/3 and Q13 1/3 -> 2/3 (refusal
  answers where a single unsupported sentence flips the verdict; with 3 runs and variable claim splitting these
  are indistinguishable from noise). Retrieval v2 should not be credited with improving groundedness.
- **Where ungrounded content lives: escalation answers.** Q9, Q10, Q11 are fully grounded in 0/3 runs in BOTH
  runs; Q20 is near 0. The unsupported claims are sensible, safety-oriented emergency instructions that no source
  contains, some carrying citations to sources that don't say them, e.g. baseline Q11 run 1: "Go to the nearest
  emergency department", "call emergency services and do not drive yourself", "Tell the medical team: ..." [1];
  baseline Q12 run 3: "Try getting extra rest, drinking fluids, and eating regularly." [1].
- **Design implication (for the escalation node):** generate the escalation message from approved source wording
  (e.g. CDC's "Seek medical care immediately") rather than letting the model write free-form emergency advice.
  Unsourced advice, however plausible, has no approver.
- **Pending audit:** borderline judge strictness, e.g. "Seek emergency medical care now" marked unsupported against
  the source's "Seek medical care immediately".

---

## Failure log

Format from `docs/eval_harness_spec.md`.

```
Question ID: Q6
Category: Comorbidity
Expected: high-risk factor ("preeclampsia in a past pregnancy"), increased recurrence risk, low-dose aspirin may be recommended
Actual: all 3 runs answered from the CHAP chronic-hypertension advisory; stated the excerpts don't cover prior preeclampsia
Root cause: Retrieval failure
  Diagnosed Day 4, before any answer existed: the phrase "ACOG guidance" matches the CHAP advisory's title and
  language ("Clinical Guidance", "ACOG recommends") better than the FAQ's topic. Removing the phrase put the
  preeclampsia FAQ at #1 with all top-10 results from it; the risk-factors chunk was outside the top 10 for the
  original wording. Hyphenated "pre-eclampsia" vs source "preeclampsia" contributes less (~0.01-0.02 distance).
Fix applied: planner query rewriting (Run 2): attribution and "guidance" words removed, spelling normalized.
  The CHAP advisory no longer appears in retrieval. The question is NOT reworded: real users phrase it this way.
Before: failed 0/3, 9 required facts missing across runs (Run 1)
After (re-run): still failed 0/3, but only 3 missing: the high-risk and recurrence facts now pass every run;
  the aspirin section ("Does low-dose aspirin prevent preeclampsia?") is still not retrieved. Next candidate:
  expanding retrieval to neighboring sections of the same document.
```

```
Question ID: Q19
Category: Multi-source synthesis
Expected: both publishers test at 24-28 weeks and earlier for higher risk; consistent; correct attribution
Actual: all 3 runs gave ACOG's guidance and said CDC's guidance was not in the provided sources (appropriate, not invented)
Root cause: Retrieval failure
  Top-5 retrieval returned only ACOG chunks (also seen Day 4). The CDC "Testing" section (p.2) never reached the
  model. The responder behaved correctly given what it had.
Fix applied: per-publisher retrieval (Run 2): when 2+ publishers are named, retrieve from each separately and
  merge by distance. CDC's Testing section now reaches the model.
Before: failed 0/3 (Run 1)
After (re-run): passed 3/3 (Run 2, adjudicated). Not yet isolated by ablation from the other Run 2 switches.
```

```
Question ID: Q5
Category: Comorbidity
Expected: prepregnancy care, glucose control before pregnancy, frequent prenatal visits, special tests to check the baby
Actual: all 3 runs covered the first three; none mentioned special tests (targeted ultrasound, tests from 32-34 weeks)
Root cause: Retrieval failure
  The "What special tests may be done during pregnancy?" chunk is not in the top 5; the answer spans several FAQ
  sections and top-5 covers only some. (Note: Q5 has 4 required facts, flagged as possibly strict when drafted. The
  key is not loosened in response to this result; the failing fact is in the source and part of the question.)
Fix applied: top_k 5 -> 8 (Run 2)
Before: failed 0/3 (Run 1)
After (re-run): still failed 0/3. The "special tests" chunk is not in the top 8 either; larger k alone does not
  fix it. Next candidate: expanding retrieval to neighboring sections of the same document.
```

Q18 is not logged as a failure: it fails by design until the Week 4 tool exists.

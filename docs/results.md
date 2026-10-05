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
Fix applied: pending (candidates: planner query rewriting that strips attribution phrases and normalizes spelling;
  header ablation; hybrid search). The question is NOT reworded: real users phrase it this way.
Before: failed 0/3
After (re-run): pending
```

```
Question ID: Q19
Category: Multi-source synthesis
Expected: both publishers test at 24-28 weeks and earlier for higher risk; consistent; correct attribution
Actual: all 3 runs gave ACOG's guidance and said CDC's guidance was not in the provided sources (appropriate, not invented)
Root cause: Retrieval failure
  Top-5 retrieval returned only ACOG chunks (also seen Day 4). The CDC "Testing" section (p.2) never reached the
  model. The responder behaved correctly given what it had.
Fix applied: pending (candidate: per-publisher retrieval, top-k from each org named in the question)
Before: failed 0/3
After (re-run): pending
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
Fix applied: pending (candidates: larger k, or expanding retrieval to neighboring sections of the same document)
Before: failed 0/3
After (re-run): pending
```

Q18 is not logged as a failure: it fails by design until the Week 4 tool exists.

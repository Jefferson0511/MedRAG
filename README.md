# MedRAG: a maternal-care guideline agent, evaluated honestly

A LangGraph agent that answers maternal and perinatal care questions from ACOG, CDC, and LactMed
source documents, with citations. The agent is a fairly standard RAG pipeline. **The point of this
project is the evaluation harness:** a source-verified answer key, repeated runs, an LLM judge whose
evidence is checked in code, human audits with adjudicated agreement, and a failure log that records
root causes and before/after numbers, including the failures that are not fixed yet.

> Not medical advice. This is a research and portfolio project over a small, fixed corpus.

## Results

Two configurations, each run 3 times per question (the responder model's temperature can't be fixed, so
a single run is a sample, not a measurement). Full detail, file paths, and audit records: [`docs/results.md`](docs/results.md).

| | Run 1: baseline RAG | Run 2: retrieval v2 |
|---|---|---|
| **Accuracy** (all required facts, no forbidden item), 17 scored questions | **39/51 runs (76%)** | **42/51 runs (82%)** |
| Accuracy excluding the tool-call question (can't pass until the live tool exists) | 39/48 (81%) | 42/48 (88%) |
| **Groundedness** (answers with zero unsupported claims), 18 questions | 30/54 (56%) | 34/54 (63%)* |
| Latency per question, median / p95 | 4.92 s / 8.02 s | 7.08 s / 11.76 s |
| Cost per full run (responder + planner) | $0.18 | $0.24 |

\* Mostly not attributable to the retrieval change: three questions moved, two of them refusal answers where
a single sentence flips the verdict. Retrieval v2 should not be credited with improving groundedness.

**What retrieval v2 changed:** a planner node rewrites the question into a content-focused search query
(removing attribution words like "per ACOG guidance" and normalizing spellings), per-publisher retrieval
when a question names several publishers, and top-k 5 to 8. It fixed the multi-source question (0/3 to 3/3),
cut the missing facts on the prior-preeclampsia question from 9 to 3, left one question unchanged, and
regressed nothing, at +44% median latency and +35% cost. These fixes were designed while looking at the eval
set's failures, so the gains are optimistic; a held-out question set would be the stronger test.

## How it's evaluated

- **Answer key** ([`docs/expected_answers.md`](docs/expected_answers.md)): for each question, the expected
  behavior (answer, escalate, refuse, or route to a tool), a checklist of required facts, forbidden items that
  fail an answer regardless (e.g. citing the superseded 160/110 blood-pressure threshold), and a verbatim quote
  with file, page, and section for every fact. Written before any LLM node existed and verified by hand
  against the PDFs. One entry was corrected during grading, from the source text, with the revision recorded.
- **Repeated runs, frozen outputs** (`src/run_eval.py`): every run is saved with the retrieved chunk pointers,
  token usage, cost, latency, configuration, and the git commit that produced it (runs from uncommitted code
  are flagged).
- **Accuracy judge** (`src/judge_accuracy.py`): Claude (`claude-opus-5-5`) grades the OpenAI responder's answers,
  so no model grades its own provider's output. It marks each checklist item with an exact quote from the
  answer; quotes are verified in code; the pass rule is applied in code, not by the judge.
- **Groundedness judge** (`src/judge_groundedness.py`): splits each answer into atomic claims and checks each
  against the sources the responder actually saw (rebuilt locally and verified against recorded headers), at
  two levels: supported by any source, and supported by the source it cites. Supporting quotes are verified in
  code against the specific source named.
- **Human audits** (`src/grade.py --audit`, `src/audit_groundedness.py`): blind (judge verdicts hidden).
  - Baseline Accuracy: every judge FAIL plus a stratified random PASS per question. Raw agreement 31/33 records
    (94%); after adjudicating all 17 item-level disagreements against the answer text, the judge matched the
    adjudicated verdict on 33/33 records. Most disagreements were human marking slips.
  - Run 2 Accuracy: the records whose verdict changed between runs. This caught the judge giving opposite
    verdicts to an identical sentence across runs; the ruling was applied to both runs.
  - Groundedness: a purposive sample of 19 claims chosen where the judge was most likely to err; it matched the
    adjudicated verdict on 19/19. Purposive, so this is a stress test, not a random-sample agreement rate.

## What fails, and why

From the failure log in [`docs/results.md`](docs/results.md):

1. **Attribution wording misdirects retrieval** (prior preeclampsia). "How does ACOG guidance differ…" matched
   the CHAP chronic-hypertension advisory's title ("Clinical Guidance…") instead of the preeclampsia FAQ.
   Diagnosed by query-variant testing before any answer existed. Query rewriting removed the wrong document;
   the low-dose aspirin section is still not retrieved, so the question still fails. The question was
   deliberately not reworded: real users phrase it this way.
2. **One publisher crowded out another** (ACOG vs CDC comparison). Top-k returned only ACOG chunks, and the
   responder correctly declined to invent CDC's side. Fixed by per-publisher retrieval.
3. **Answers spanning several sections** (pregestational diabetes). The "special tests" section isn't retrieved
   at k=5 or k=8. Not fixed.
4. **Ungrounded emergency advice** (the escalation questions). The agent escalates correctly every time, but
   0/9 escalation answers are fully grounded in either run: it adds its own instructions ("go to the nearest
   emergency department", "do not drive yourself", "seek *emergency* care" where the source says "seek medical
   care immediately"), some carrying citations to sources that don't say them. Retrieval changes didn't touch
   this; it's a generation problem. Next fix candidate: build escalation messages from approved source wording.

Every Accuracy failure in the baseline was a retrieval failure: when the right chunks were retrieved, the
baseline answered, escalated, held back from over-escalating, and refused correctly.

## Limitations

- 18 scored questions over 12 source documents. Small, and the fixes were developed on the same questions.
- Two of the planned tool-call questions are placeholders until the live LactMed/PubMed tool exists; the third
  fails by design until then.
- One judge model, audited on targeted samples rather than the full set.
- Safety (informational vs prescriptive language) is not yet scored as a separate rubric dimension.
- Results reflect one responder model at default temperature; another model could rank differently.

## Architecture

```
START -> plan -> retrieve -> respond -> END        (Run 2; Run 1 has no plan node)
```

- **Ingestion:** PDFs extracted with pypdf layout mode (default mode reordered FAQ headings away from their
  answers), publisher-specific boilerplate removal (each rule audited before use), section-aware chunking that
  keeps every FAQ question with its answer, context headers (`ACOG | title | category | question`), and page
  ranges for citations.
- **Retrieval:** `text-embedding-3-small` vectors in Postgres + pgvector via `langchain-postgres` (`PGVectorStore`),
  metadata as real columns, publisher filtering.
- **Agent:** LangGraph state graph; responder `gpt-6.1-sol`, planner `gpt-6-luna`. Every switch (`rewrite`,
  `per_publisher`, `top_k`) is independent so each change can be measured.

Planned next: grounding and escalation nodes measured against Run 2, then a live LactMed/PubMed tool over MCP.

## Running it

Requires Python 3.11, Docker, an OpenAI API key (responder, planner, embeddings) and an Anthropic API key (judges).

```powershell
copy .env.example .env               # then fill in the Postgres password and both API keys
docker compose up -d                 # Postgres 16 + pgvector
python -m venv .venv; .venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python scripts\check_db.py           # sanity check: pgvector works
```

Source PDFs are copyrighted and not in the repo. `data/SOURCES.md` lists every file, URL, and access date
needed to rebuild the corpus into `data/raw/{acog,cdc,lactmed}/`.

```powershell
python src\ingest.py                                   # load, clean, chunk, embed (asks before spending)
python src\retrieve.py --q 4                           # see what retrieval returns for an eval question
python src\agent.py --q 19 --rewrite --per-publisher --k 8
python src\run_eval.py --label my_run --rewrite --per-publisher --k 8
python src\judge_accuracy.py results\my_run_<timestamp>.jsonl
python src\judge_groundedness.py results\my_run_<timestamp>.jsonl
```

## Repository

```
data/SOURCES.md            corpus provenance and eval coverage matrix
docs/eval_harness_spec.md  question bank, rubric, failure-log format
docs/expected_answers.md   verified answer key with verbatim source evidence
docs/results.md            every run, audit, and failure-log entry
results/                   frozen run outputs, judge grades, human grades, adjudications
src/                       loader, chunker, ingest, retrieval, agent, runner, judges, audit tools
```

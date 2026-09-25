# Learning log — maternal care guideline agent

Running notes on every concept and framework used in this project, written in my own
words as I learn them. Updated as the build progresses, not written after the fact.
Purpose: prove I understand what I built, not just that I copied a working pipeline.

---

## How to use this file

Each concept gets: what it is, why this project needs it, and anything I got wrong
at first and had to correct. Wrong-first-understanding entries stay in, crossed out,
not deleted, that's part of the record.

---

## Concepts

### RAG (Retrieval-Augmented Generation)
**Status: learned**

**What it is:** instead of an LLM answering from memorized training data, you retrieve
the actual relevant document at question time and hand it to the model to read and
answer from. Open-book exam, not memorized exam.

**Why this project needs it:** an LLM can't have ACOG/CDC guidelines memorized reliably,
and guidelines update. RAG means the agent answers from the current, real document
instead of guessing from stale training data.

**Two phases, don't confuse them:**
- Indexing (offline, done once): documents -> chunks -> embeddings -> vector store
- Query time (every question): question -> embed -> similarity search -> retrieve
  top-k chunks -> augment prompt -> LLM generates grounded answer

**Key terms:**
- Chunking: splitting documents into small passages, because embedding a whole
  200-page guideline as one unit makes retrieval useless
- Embedding: converting text into a vector of numbers positioned so similar-meaning
  text ends up close together in vector space. Not keyword matching, meaning matching.
- Top-k: how many closest chunks to retrieve per question (commonly 3-5)
- Groundedness: whether every claim in the answer is actually traceable to a
  retrieved chunk, separate from whether the final answer happens to be correct

---

### LangChain
**Status: not yet started**

**What it is:** _fill in once we start using it_

**Why this project needs it:** _fill in_

---

### LangGraph
**Status: not yet started**

**What it is:** _fill in once we build the planner/retriever/responder nodes_

**Why this project needs it over plain LangChain:** _fill in_

---

### pgvector
**Status: not yet started**

**What it is:** _fill in_

**Why this project uses it instead of a hosted vector DB:** _fill in_

---

### Embeddings and cosine similarity (the math)
**Status: not yet started**

**What it is:** _fill in — the actual math behind "closest in vector space"_

---

### MCP (Model Context Protocol)
**Status: not yet started**

**What it is:** _fill in_

**Why this project needs it separately from RAG:** _fill in — RAG retrieves documents,
MCP lets the agent take actions or fetch structured data beyond the document store_

---

### Eval harness design
**Status: spec written, not yet implemented**

**What it is:** _fill in once we implement the scoring code_

See `eval_harness_spec.md` for the full question bank and rubric.

---

## Project log (by week)

### Week 0 — planning
- Locked domain: maternal/perinatal care guideline agent (ACOG, CDC, LactMed corpus)
- Reasoning: matches a live Elevare Health application, more advanced JD pattern
  (adds escalation logic) than the earlier diabetes-domain plan
- Wrote eval harness spec: 20 questions across 6 categories, 6-dimension rubric
- Honest self-check: the RAG/LangChain skeleton is common, the eval rigor and
  documented failure analysis is the actual differentiator, not the architecture

### Week 1 — corpus + ingestion
_fill in as this happens_

### Week 2 — LangGraph nodes
_fill in_

### Week 3 — escalation node + baseline eval run
_fill in_

### Week 4 — MCP tool integration
_fill in_

### Week 5 — packaging + demo
_fill in_

---

## Things I got wrong at first

_Log here whenever I misunderstand something and correct it. This is not a place to
clean up your thinking retroactively, it's a place to show the actual learning curve._
# Maternal Care Guideline Agent

A LangGraph agent that answers maternal/perinatal care questions grounded in
ACOG, CDC, and LactMed sources, with an eval harness scoring accuracy,
groundedness, safety, escalation correctness, latency, and cost.

**Status:** Week 1, Day 1 — environment setup.

See `docs/LEARNING_LOG.md` for running notes and `docs/eval_harness_spec.md`
for the evaluation design.

## Local setup
1. `cp .env.example .env` and set a password
2. `docker compose up -d`
3. `python -m venv .venv && source .venv/bin/activate`
4. `pip install -r requirements.txt`
5. `python scripts/check_db.py`

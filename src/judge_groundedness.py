"""Groundedness grading: is every claim an answer makes backed by the sources it was given?

Two levels per claim:
- supported:      backed by ANY retrieved source (if not, the model added it from training data)
- cited_supports: if the claim cites [n], does a cited source back it (Q4: supported by [2], cited to [1])

Results files store chunk pointers, not chunk text (the corpus is copyrighted), so the sources are rebuilt
locally from the loader and chunker, checked against the recorded headers, and formatted with the agent's
own format_sources(), so the judge sees exactly what the responder saw.

    python src/judge_groundedness.py results/baseline_20261002T214349Z.jsonl --q 4 12   (smoke test)
    python src/judge_groundedness.py results/baseline_20261002T214349Z.jsonl
"""
import argparse
import json
from datetime import date
from pathlib import Path

import anthropic
from dotenv import load_dotenv
from langchain_core.documents import Document
from pydantic import BaseModel

from agent import MODEL_PRICES, format_sources
from chunker import chunk_body, chunk_documents
from judge_accuracy import normalize
from loader import load_corpus
from retrieve import RetrievedChunk
from run_eval import git_state

JUDGE_MODEL = "claude-opus-5-5"
JUDGE_EFFORT = "high"
# v2 (after the smoke test): explicit citation-scope rule. v1 attached a paragraph-final [n] only to its own
# sentence, so earlier claims in the paragraph counted as uncited and their citations were never checked.
JUDGE_PROMPT_VERSION = "groundedness-v2"
ESTIMATED_USD_PER_RECORD = 0.035

JUDGE_SYSTEM_PROMPT = """You check whether a medical assistant's answer is grounded in the numbered sources it was given.

1. Split the answer into atomic factual claims: each one a single checkable statement.
   Skip statements that are only about the sources themselves ("the sources don't mention X"),
   restatements of the question, and pure framing. Keep advice and recommendations: they are claims.
2. For each claim:
   - answer_quote: copy the exact span of the answer that makes the claim, character for character.
   - cited_sources: the [n] numbers that apply to that claim, [] if none. Citation scope: a marker applies to
     the sentence it ends AND to any earlier sentences in the same paragraph or bullet that carry no marker
     of their own. A marker never applies across paragraphs or bullets.
   - supported: true only if at least one source states it or directly entails it. Judge ONLY against the
     sources. A claim that is medically true but not in the sources is NOT supported.
   - supporting_source and supporting_quote: for a supported claim, the source number and an exact passage
     from that source that backs it, copied character for character. For an unsupported claim: null and "".
   - cited_supports: if cited_sources is non-empty, true if at least one CITED source backs the claim,
     false otherwise. null if the claim has no citation."""


class ClaimVerdict(BaseModel):
    """One atomic claim from the answer and whether the sources back it."""
    answer_quote: str
    cited_sources: list[int]
    supported: bool
    supporting_source: int | None
    supporting_quote: str
    cited_supports: bool | None


class GroundednessJudgment(BaseModel):
    """Every factual claim in one answer, checked against its sources."""
    claims: list[ClaimVerdict]


def chunk_lookup() -> dict[tuple[str, int], Document]:
    """Rebuild every chunk locally (deterministic, no API cost), keyed the way run records point to them."""
    chunks = chunk_documents(load_corpus(Path("data/raw")))
    return {(c.metadata["source"], c.metadata["chunk_index"]): c for c in chunks}


def rebuild_sources(record: dict, lookup: dict[tuple[str, int], Document]) -> list[RetrievedChunk]:
    """The exact chunks the responder saw, in order. Fails loudly if chunking changed since the run."""
    rebuilt = []
    for pointer in record["retrieved"]:
        chunk = lookup.get((pointer["source"], pointer["chunk_index"]))
        if chunk is None or chunk.metadata["header"] != pointer["header"]:
            raise ValueError(f"chunk {pointer['source']}#{pointer['chunk_index']} changed since the run")
        rebuilt.append(RetrievedChunk(chunk, pointer["distance"]))
    return rebuilt


def judge_record(client: anthropic.Anthropic, record: dict, sources: list[RetrievedChunk]) -> dict:
    """Ask the judge for claim-level verdicts, verify every quote in code, and compute the metrics."""
    response = client.messages.parse(
        model=JUDGE_MODEL,
        max_tokens=16000,
        system=JUDGE_SYSTEM_PROMPT,
        output_config={"effort": JUDGE_EFFORT},
        output_format=GroundednessJudgment,
        messages=[{
            "role": "user",
            "content": f"SOURCES:\n\n{format_sources(sources)}\n\nQUESTION: {record['question']}\n\nANSWER:\n{record['answer']}",
        }],
    )
    if response.stop_reason == "refusal":
        raise RuntimeError(f"judge refused: {response.stop_details}")
    judgment: GroundednessJudgment = response.parsed_output

    answer_normalized = normalize(record["answer"])
    source_texts = [normalize(chunk_body(chunk.document)) for chunk in sources]  # [n] -> source_texts[n-1]
    claims = []
    for verdict in judgment.claims:
        quote_in_answer = normalize(verdict.answer_quote) in answer_normalized
        support_ok = True
        if verdict.supported:  # a supported verdict must quote real text from the source it names
            index = (verdict.supporting_source or 0) - 1
            support_ok = 0 <= index < len(source_texts) and bool(verdict.supporting_quote) \
                and normalize(verdict.supporting_quote) in source_texts[index]
        claims.append({**verdict.model_dump(), "quote_in_answer": quote_in_answer, "support_quote_ok": support_ok})

    unsupported = [c for c in claims if not c["supported"]]
    cited = [c for c in claims if c["cited_sources"]]
    input_price, output_price = MODEL_PRICES[JUDGE_MODEL]
    cost = response.usage.input_tokens / 1e6 * input_price + response.usage.output_tokens / 1e6 * output_price
    return {
        "claims": claims,
        "n_claims": len(claims),
        "n_unsupported": len(unsupported),
        "grounded": not unsupported,  # binary per answer: zero unsupported claims
        "n_cited": len(cited),
        "n_cited_correct": sum(1 for c in cited if c["cited_supports"]),
        "all_evidence_ok": all(c["quote_in_answer"] and c["support_quote_ok"] for c in claims),
        "usage": {"input_tokens": response.usage.input_tokens, "output_tokens": response.usage.output_tokens},
        "cost_usd": round(cost, 6),
    }


def summarize(grades: list[dict]) -> None:
    """Run-level groundedness metrics."""
    ok = [g for g in grades if not g.get("error")]
    if not ok:
        print("no successful grades")
        return
    claims = sum(g["n_claims"] for g in ok)
    unsupported = sum(g["n_unsupported"] for g in ok)
    cited = sum(g["n_cited"] for g in ok)
    cited_correct = sum(g["n_cited_correct"] for g in ok)
    print(f"\nGroundedness per the judge (UNAUDITED), {len(ok)} answers:")
    print(f"  answers fully grounded:  {sum(g['grounded'] for g in ok)}/{len(ok)} ({sum(g['grounded'] for g in ok) / len(ok):.0%})")
    print(f"  unsupported claims:      {unsupported}/{claims} ({unsupported / claims:.1%})" if claims else "  no claims")
    print(f"  citation precision:      {cited_correct}/{cited} ({cited_correct / cited:.1%})" if cited else "  no citations")
    print(f"  records with unverifiable evidence: {sum(not g['all_evidence_ok'] for g in ok)}")
    print(f"  cost: ${sum(g['cost_usd'] for g in ok):.4f}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="LLM-judge groundedness grading of a frozen run.")
    parser.add_argument("run_file", type=Path, help="results/<label>_<timestamp>.jsonl from run_eval.py")
    parser.add_argument("--q", type=int, nargs="*", help="only these question numbers (e.g. for a smoke test)")
    args = parser.parse_args()

    load_dotenv()
    records = [json.loads(line) for line in args.run_file.read_text(encoding="utf-8").splitlines()]
    records = [r for r in records if not r["error"] and r["question_id"] in (args.q or [r["question_id"]])]

    out_path = args.run_file.with_name(f"groundedness_{args.run_file.stem}.jsonl")
    existing = [json.loads(line) for line in out_path.read_text(encoding="utf-8").splitlines()] \
        if out_path.exists() else []
    # only grades from the CURRENT prompt version count as done; older versions stay in the file for the record
    existing = [g for g in existing if g.get("judge_prompt_version") == JUDGE_PROMPT_VERSION]
    done = {(g["question_id"], g["run_index"]) for g in existing if not g.get("error")}
    todo = [r for r in records if (r["question_id"], r["run_index"]) not in done]

    commit, dirty = git_state()
    if dirty:
        print("WARNING: uncommitted changes; these grades won't be reproducible from a commit.")
    answer = input(f"Judge {len(todo)} records with {JUDGE_MODEL} (about ${len(todo) * ESTIMATED_USD_PER_RECORD:.2f})? [y/N] ")
    if answer.strip().lower() != "y":
        raise SystemExit("Cancelled, nothing was judged.")

    lookup = chunk_lookup()
    client = anthropic.Anthropic()
    grades = [g for g in existing if not g.get("error")]
    with out_path.open("a", encoding="utf-8") as out_file:
        for record in todo:
            grade = {
                "run_file": args.run_file.name, "question_id": record["question_id"], "run_index": record["run_index"],
                "grader": f"llm-judge:{JUDGE_MODEL}", "judge_effort": JUDGE_EFFORT,
                "judge_prompt_version": JUDGE_PROMPT_VERSION, "graded_on": date.today().isoformat(),
                "git_commit": commit, "git_dirty": dirty, "error": None,
            }
            try:
                grade.update(judge_record(client, record, rebuild_sources(record, lookup)))
            except Exception as error:  # recorded and retried on the next run
                grade["error"] = f"{type(error).__name__}: {error}"
            out_file.write(json.dumps(grade, ensure_ascii=False) + "\n")
            out_file.flush()
            if grade["error"]:
                print(f"  Q{record['question_id']} run {record['run_index']}: {grade['error']}")
                continue
            grades.append(grade)
            flag = "" if grade["all_evidence_ok"] else "  <- CHECK (unverifiable quote)"
            print(f"  Q{record['question_id']} run {record['run_index']}: {grade['n_unsupported']}/{grade['n_claims']} "
                  f"unsupported, citations {grade['n_cited_correct']}/{grade['n_cited']} correct{flag}")
    summarize(grades)

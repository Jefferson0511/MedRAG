"""Run the agent over the eval question bank and freeze every output to a JSONL file.

No grading happens here. Each record captures exactly what the system did (answer, retrieved
chunk metadata, tokens, cost, latency, code version) so grading can happen later, repeatedly,
against an output that can't silently change.

    python src/run_eval.py                    all concrete questions, 3 runs each
    python src/run_eval.py --runs 1 --q 4 13  quick check on specific questions
"""
import argparse
import json
import statistics
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

from agent import MODEL_PRICES, RESPONDER_MODEL, build_graph
from retrieve import load_eval_questions
from vectorstore import open_store

RESULTS_DIR = Path("results")
ESTIMATED_USD_PER_CALL = 0.003  # from the first runs: ~750 input + ~50-240 output tokens on gpt-6.1-sol


def git_state() -> tuple[str, bool]:
    """(commit hash, dirty?) so every result records which code produced it."""
    commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    # untracked files (like results/ itself) don't change the code that ran, so they don't count as dirty
    dirty = bool(subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"],
                                capture_output=True, text=True).stdout.strip())
    return commit, dirty


def cost_usd(usage: list[dict]) -> float:
    """Sum the cost of every LLM call recorded in the state's usage log."""
    total = 0.0
    for record in usage:
        input_price, output_price = MODEL_PRICES[record["model"]]
        total += record["input_tokens"] / 1e6 * input_price + record["output_tokens"] / 1e6 * output_price
    return total


def retrieved_metadata(retrieved: list) -> list[dict]:
    """Chunk pointers only, no chunk text: results are committed and the corpus is copyrighted."""
    return [
        {
            "rank": rank,
            "distance": round(distance, 4),
            "source": document.metadata["source"],
            "chunk_index": document.metadata["chunk_index"],
            "header": document.metadata["header"],
            "page_start": document.metadata["page_start"],
            "page_end": document.metadata["page_end"],
        }
        for rank, (document, distance) in enumerate(retrieved, start=1)
    ]


def summarize(records: list[dict]) -> None:
    """Print record/error counts, median and p95 latency, total tokens and cost."""
    ok = [r for r in records if not r["error"]]
    print(f"\n{len(records)} records, {len(records) - len(ok)} errors")
    if not ok:
        return
    latencies = [r["latency_s"] for r in ok]
    p95 = statistics.quantiles(latencies, n=20)[18] if len(latencies) >= 2 else latencies[0]
    tokens = sum(u["input_tokens"] + u["output_tokens"] for r in ok for u in r["usage"])
    print(f"latency: median {statistics.median(latencies):.2f}s, p95 {p95:.2f}s")
    print(f"tokens: {tokens}, cost: ${sum(r['cost_usd'] for r in ok):.4f}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the agent over eval questions and save raw outputs.")
    parser.add_argument("--runs", type=int, default=3, help="runs per question (temperature can't be fixed)")
    parser.add_argument("--q", type=int, nargs="*", help="only these question numbers (default: all concrete)")
    parser.add_argument("--label", default="baseline", help="name for this configuration, used in the filename")
    args = parser.parse_args()

    load_dotenv()
    questions = load_eval_questions()
    if args.q:
        questions = {number: questions[number] for number in args.q}

    commit, dirty = git_state()
    if dirty:
        print("WARNING: uncommitted changes; these results won't be reproducible from a commit.")
    calls = len(questions) * args.runs
    answer = input(f"Run {len(questions)} questions x {args.runs} runs = {calls} calls "
                   f"(about ${calls * ESTIMATED_USD_PER_CALL:.3f})? [y/N] ")
    if answer.strip().lower() != "y":
        raise SystemExit("Cancelled, nothing was run.")

    graph = build_graph(open_store(), ChatOpenAI(model=RESPONDER_MODEL))
    RESULTS_DIR.mkdir(exist_ok=True)
    started = datetime.now(timezone.utc)
    out_path = RESULTS_DIR / f"{args.label}_{started.strftime('%Y%m%dT%H%M%SZ')}.jsonl"

    records: list[dict] = []
    with out_path.open("w", encoding="utf-8") as out_file:
        for number, question in questions.items():
            for run_index in range(1, args.runs + 1):
                record = {
                    "run_label": args.label, "question_id": number, "run_index": run_index,
                    "question": question, "model": RESPONDER_MODEL,
                    "git_commit": commit, "git_dirty": dirty,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "answer": None, "retrieved": [], "usage": [], "cost_usd": 0.0, "latency_s": None, "error": None,
                }
                start = time.perf_counter()
                try:
                    state = graph.invoke({"question": question, "usage": []})
                    record.update(
                        answer=state["answer"],
                        retrieved=retrieved_metadata(state["retrieved"]),
                        usage=state["usage"],
                        cost_usd=round(cost_usd(state["usage"]), 6),
                    )
                except Exception as error:  # record and keep going: one failed call shouldn't kill the run
                    record["error"] = f"{type(error).__name__}: {error}"
                record["latency_s"] = round(time.perf_counter() - start, 3)
                out_file.write(json.dumps(record, ensure_ascii=False) + "\n")
                out_file.flush()  # on disk now, so a crash later doesn't lose finished runs
                records.append(record)
                status = "ERROR" if record["error"] else f"{record['latency_s']:.1f}s"
                print(f"  Q{number} run {run_index}: {status}")

    print(f"\nSaved {out_path}")
    summarize(records)

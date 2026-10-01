"""Retrieve the top-k chunks for a question. Used by the Week 2 retriever node and for eval diagnostics.

    python src/retrieve.py --q 4            one eval question, top 5 with text previews
    python src/retrieve.py --all            every eval question, top 3 headers each
    python src/retrieve.py "any question"   ad-hoc query
    python src/retrieve.py --q 19 --org cdc restrict to one publisher
"""
import argparse
import re
from pathlib import Path
from typing import NamedTuple

from dotenv import load_dotenv
from langchain_core.documents import Document
from langchain_postgres import PGVectorStore

from vectorstore import open_store

EVAL_SPEC = Path("docs/eval_harness_spec.md")


class RetrievedChunk(NamedTuple):
    """A retrieved chunk and its cosine DISTANCE to the query (lower = more similar)."""
    document: Document
    distance: float


def retrieve(store: PGVectorStore, query: str, k: int = 5, org: str | None = None) -> list[RetrievedChunk]:
    """Top-k chunks by cosine distance, optionally restricted to one publisher ("acog", "cdc", "lactmed")."""
    results = store.similarity_search_with_score(query, k=k, filter={"org": org} if org else None)
    return [RetrievedChunk(document, distance) for document, distance in results]


def load_eval_questions(spec_path: Path = EVAL_SPEC) -> dict[int, str]:
    """Read the question bank straight from the eval spec, so the spec stays the single source of truth."""
    questions: dict[int, str] = {}
    for line in spec_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## Scoring rubric"):
            break  # numbered lines after this point are the build order, not questions
        # only unindented numbered lines are questions; indented "-" notes are never sent to the agent
        match = re.match(r"^(\d+)\. (.+)$", line)
        if match and not match.group(2).startswith("[placeholder]"):  # not concrete yet, skip
            questions[int(match.group(1))] = match.group(2)
    return questions


def print_results(results: list[RetrievedChunk], preview_chars: int) -> None:
    """One line per result; optionally a preview of the chunk body (the header is already shown)."""
    for rank, (document, distance) in enumerate(results, start=1):
        meta = document.metadata
        print(f"  #{rank} distance={distance:.4f} | {meta['header']} | pages {meta['page_start']}-{meta['page_end']}")
        if preview_chars:
            body = document.page_content.split("\n\n", 1)[-1]  # drop the header line we already printed
            print(f"      {body[:preview_chars].replace(chr(10), ' ')}...")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Retrieve top-k chunks for a question.")
    parser.add_argument("query", nargs="?", help="an ad-hoc question (omit when using --q or --all)")
    parser.add_argument("--q", type=int, help="eval question number from docs/eval_harness_spec.md")
    parser.add_argument("--all", action="store_true", help="run every eval question (top 3 headers each)")
    parser.add_argument("--k", type=int, default=5, help="number of chunks to retrieve (default 5)")
    parser.add_argument("--org", choices=["acog", "cdc", "lactmed"], help="restrict to one publisher")
    args = parser.parse_args()

    load_dotenv()
    store = open_store()

    if args.all:
        for number, question in load_eval_questions().items():
            print(f"\nQ{number}: {question}")
            print_results(retrieve(store, question, k=3, org=args.org), preview_chars=0)
    else:
        if args.q is not None:
            question = load_eval_questions()[args.q]
            print(f"Q{args.q}: {question}")
        elif args.query:
            question = args.query
            print(f"Query: {question}")
        else:
            parser.error("give a question, --q N, or --all")
        print_results(retrieve(store, question, k=args.k, org=args.org), preview_chars=200)

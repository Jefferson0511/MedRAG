"""Baseline agent: START -> retrieve -> respond -> END.

Deliberately plain RAG: no planner, no grounding check, no escalation. Its eval scores are the
"before" numbers that every later node is measured against.

    python src/agent.py --q 4            one eval question
    python src/agent.py "any question"   ad-hoc question
"""
import argparse
import operator
from typing import Annotated, TypedDict

from dotenv import load_dotenv
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langchain_postgres import PGVectorStore
from langgraph.graph import END, START, StateGraph

from chunker import chunk_body
from retrieve import RetrievedChunk, load_eval_questions, retrieve
from vectorstore import open_store

# Checked on OpenAI's models page 2026-10-02: $2 / $10 per 1M input/output tokens.
# This model only accepts the default temperature (1), so answers vary between runs;
# the eval runner must repeat each question rather than trust a single run.
RESPONDER_MODEL = "gpt-6.1-sol"
TOP_K = 5

# Baseline prompt: answer from sources and cite them. It does NOT tell the model to refuse when
# the sources don't cover the question. Refusal is the grounding checker's job, and putting it
# here would hide that node's contribution inside the baseline.
RESPONDER_SYSTEM_PROMPT = (
    "You answer questions about maternal and perinatal care using the numbered sources provided. "
    "Cite the sources you use inline by number, like [1] or [2][3]."
)


class AgentState(TypedDict):
    """Shared state passed through the graph. Each node returns only the keys it changes."""
    question: str
    retrieved: list[RetrievedChunk]
    answer: str
    # reducer: each LLM-calling node APPENDS a usage record instead of overwriting the list
    usage: Annotated[list[dict], operator.add]


def format_sources(retrieved: list[RetrievedChunk]) -> str:
    """Number each chunk so the model can cite it: '[1] header (pages x-y)' followed by its text."""
    blocks = []
    for number, (document, _distance) in enumerate(retrieved, start=1):
        meta = document.metadata
        blocks.append(
            f"[{number}] {meta['header']} (pages {meta['page_start']}-{meta['page_end']})\n"
            f"{chunk_body(document)}"  # page_content already starts with the header; don't repeat it
        )
    return "\n\n".join(blocks)


def build_graph(store: PGVectorStore, llm: BaseChatModel, model_name: str = RESPONDER_MODEL):
    """Compile the baseline graph. Nodes are closures over store and llm, so the eval harness can
    swap either one (e.g. the MiniLM table, or another model) without touching node code."""

    def retrieve_node(state: AgentState) -> dict:
        return {"retrieved": retrieve(store, state["question"], k=TOP_K)}

    def respond_node(state: AgentState) -> dict:
        message = llm.invoke([
            SystemMessage(RESPONDER_SYSTEM_PROMPT),
            HumanMessage(f"Sources:\n\n{format_sources(state['retrieved'])}\n\nQuestion: {state['question']}"),
        ])
        usage = message.usage_metadata or {}
        return {
            "answer": message.content,
            "usage": [{
                "node": "respond",
                "model": model_name,
                "input_tokens": usage.get("input_tokens", 0),
                "output_tokens": usage.get("output_tokens", 0),
            }],
        }

    builder = StateGraph(AgentState)
    builder.add_node("retrieve", retrieve_node)
    builder.add_node("respond", respond_node)
    builder.add_edge(START, "retrieve")
    builder.add_edge("retrieve", "respond")
    builder.add_edge("respond", END)
    return builder.compile()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ask the baseline agent a question.")
    parser.add_argument("query", nargs="?", help="an ad-hoc question (omit when using --q)")
    parser.add_argument("--q", type=int, help="eval question number from docs/eval_harness_spec.md")
    args = parser.parse_args()

    load_dotenv()
    if args.q is not None:
        question = load_eval_questions()[args.q]
    elif args.query:
        question = args.query
    else:
        parser.error("give a question or --q N")

    graph = build_graph(open_store(), ChatOpenAI(model=RESPONDER_MODEL))
    final_state = graph.invoke({"question": question, "usage": []})

    print(f"Question: {question}\n")
    print(final_state["answer"])
    print("\nSources given to the model:")
    for number, (document, distance) in enumerate(final_state["retrieved"], start=1):
        meta = document.metadata
        print(f"  [{number}] distance={distance:.4f} | {meta['header']} | pages {meta['page_start']}-{meta['page_end']}")
    for record in final_state["usage"]:
        print(f"\nUsage: {record}")

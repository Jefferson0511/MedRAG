"""The agent graph.

Defaults reproduce the Run 1 baseline exactly: START -> retrieve -> respond -> END, top-5 retrieval,
no planner. Retrieval v2 changes are independent switches, so each one's effect can be measured:

- rewrite:       add a plan node that rewrites the question into a topic-focused search query and
                 extracts explicitly named publishers (START -> plan -> retrieve -> respond -> END)
- per_publisher: when 2+ publishers are named, retrieve the top results from each one separately
- top_k:         how many chunks the responder sees

    python src/agent.py --q 4                                   baseline
    python src/agent.py --q 19 --rewrite --per-publisher --k 8  retrieval v2
"""
import argparse
import math
import operator
from typing import Annotated, Literal, TypedDict

from dotenv import load_dotenv
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langchain_postgres import PGVectorStore
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel

from chunker import chunk_body
from retrieve import RetrievedChunk, load_eval_questions, retrieve
from vectorstore import open_store

# Checked on OpenAI's models page 2026-10-02: $2 / $10 per 1M input/output tokens.
# This model only accepts the default temperature (1), so answers vary between runs;
# the eval runner must repeat each question rather than trust a single run.
RESPONDER_MODEL = "gpt-6.1-sol"
PLANNER_MODEL = "gpt-6-luna"  # cheap and fast: query rewriting is a small, frequent job
TOP_K = 5  # baseline value; retrieval v2 passes a different top_k explicitly

# USD per 1M (input, output) tokens. One table, so every cost number comes from the same place.
MODEL_PRICES = {
    "gpt-6.1-sol": (2.00, 10.00),  # OpenAI models page, checked 2026-10-02
    "gpt-6-astra": (10.00, 50.00),  # OpenAI models page, checked 2026-10-02
    "gpt-6-luna": (0.10, 0.50),  # OpenAI models page, checked 2026-10-02 (planner)
    "claude-opus-5-5": (4.00, 20.00),  # Anthropic model table, checked 2026-10-04 (Accuracy judge)
}

# Baseline prompt: answer from sources and cite them. It does NOT tell the model to refuse when
# the sources don't cover the question. Refusal is the grounding checker's job, and putting it
# here would hide that node's contribution inside the baseline.
RESPONDER_SYSTEM_PROMPT = (
    "You answer questions about maternal and perinatal care using the numbered sources provided. "
    "Cite the sources you use inline by number, like [1] or [2][3]."
)

PLANNER_SYSTEM_PROMPT = """You prepare a user's question for searching an index of maternal and perinatal care guideline excerpts.

search_query: rewrite the question as a search query about its medical CONTENT.
- Keep the condition, population, timing, and what is being asked.
- Remove every reference to who issued the guidance and words about guidance itself: names of
  organizations, "per ...", "according to ...", "guidance", "guidelines", "recommendations", "advice".
  Those words describe the source, not the content, and they mislead the search.
- Use standard spellings of medical terms (for example "preeclampsia", not "pre-eclampsia").
- Do not answer the question and do not add facts that are not in it.

publishers: list only the publishers the user EXPLICITLY names: "acog", "cdc", "lactmed". Empty if none."""


class Plan(BaseModel):
    """The planner's output: a content-focused search query and the publishers the user named."""
    search_query: str
    publishers: list[Literal["acog", "cdc", "lactmed"]]  # Literal: only these exact values are allowed


class AgentState(TypedDict, total=False):
    """Shared state passed through the graph. Each node returns only the keys it changes.
    total=False: keys like search_query exist only when the plan node runs."""
    question: str
    search_query: str
    publishers: list[str]
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


def usage_record(node: str, model: str, message) -> dict:
    """Token usage for one LLM call, appended to state['usage'] by the reducer."""
    usage = getattr(message, "usage_metadata", None) or {}
    return {"node": node, "model": model,
            "input_tokens": usage.get("input_tokens", 0), "output_tokens": usage.get("output_tokens", 0)}


def build_graph(
    store: PGVectorStore,
    llm: BaseChatModel,
    model_name: str = RESPONDER_MODEL,
    rewrite: bool = False,
    per_publisher: bool = False,
    top_k: int = TOP_K,
    planner_llm: BaseChatModel | None = None,
):
    """Compile the agent graph. Defaults reproduce the baseline. Nodes are closures over store and the
    LLMs, so the eval harness can swap any of them without touching node code."""
    if rewrite and planner_llm is None:
        planner_llm = ChatOpenAI(model=PLANNER_MODEL)
    planner = planner_llm.with_structured_output(Plan, include_raw=True) if rewrite else None

    def plan_node(state: AgentState) -> dict:
        response = planner.invoke([SystemMessage(PLANNER_SYSTEM_PROMPT), HumanMessage(state["question"])])
        plan: Plan = response["parsed"]
        return {
            "search_query": plan.search_query,
            "publishers": sorted(set(plan.publishers)),
            "usage": [usage_record("plan", PLANNER_MODEL, response["raw"])],
        }

    def retrieve_node(state: AgentState) -> dict:
        query = state.get("search_query") or state["question"]  # rewritten query only for retrieval
        publishers = state.get("publishers") or []
        # 2+ named publishers: search each separately so one can't crowd the other out (Q19).
        # A single named publisher is NOT used as a filter: users can name the wrong source (Q1 once did).
        if per_publisher and len(publishers) >= 2:
            per_org = math.ceil(top_k / len(publishers))
            merged = [chunk for org in publishers for chunk in retrieve(store, query, k=per_org, org=org)]
            return {"retrieved": sorted(merged, key=lambda chunk: chunk.distance)[:top_k]}
        return {"retrieved": retrieve(store, query, k=top_k)}

    def respond_node(state: AgentState) -> dict:
        # the responder answers the user's ORIGINAL question; the search query is only for retrieval
        message = llm.invoke([
            SystemMessage(RESPONDER_SYSTEM_PROMPT),
            HumanMessage(f"Sources:\n\n{format_sources(state['retrieved'])}\n\nQuestion: {state['question']}"),
        ])
        return {"answer": message.content, "usage": [usage_record("respond", model_name, message)]}

    builder = StateGraph(AgentState)
    builder.add_node("retrieve", retrieve_node)
    builder.add_node("respond", respond_node)
    if rewrite:
        builder.add_node("plan", plan_node)
        builder.add_edge(START, "plan")
        builder.add_edge("plan", "retrieve")
    else:
        builder.add_edge(START, "retrieve")
    builder.add_edge("retrieve", "respond")
    builder.add_edge("respond", END)
    return builder.compile()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ask the agent a question.")
    parser.add_argument("query", nargs="?", help="an ad-hoc question (omit when using --q)")
    parser.add_argument("--q", type=int, help="eval question number from docs/eval_harness_spec.md")
    parser.add_argument("--rewrite", action="store_true", help="add the plan node (query rewriting)")
    parser.add_argument("--per-publisher", action="store_true", help="per-publisher retrieval when 2+ are named")
    parser.add_argument("--k", type=int, default=TOP_K, help=f"chunks given to the responder (default {TOP_K})")
    args = parser.parse_args()

    load_dotenv()
    if args.q is not None:
        question = load_eval_questions()[args.q]
    elif args.query:
        question = args.query
    else:
        parser.error("give a question or --q N")

    graph = build_graph(open_store(), ChatOpenAI(model=RESPONDER_MODEL),
                        rewrite=args.rewrite, per_publisher=args.per_publisher, top_k=args.k)
    final_state = graph.invoke({"question": question, "usage": []})

    print(f"Question: {question}")
    if "search_query" in final_state:
        print(f"Search query: {final_state['search_query']} | publishers: {final_state['publishers']}")
    print(f"\n{final_state['answer']}")
    print("\nSources given to the model:")
    for number, (document, distance) in enumerate(final_state["retrieved"], start=1):
        meta = document.metadata
        print(f"  [{number}] distance={distance:.4f} | {meta['header']} | pages {meta['page_start']}-{meta['page_end']}")
    for record in final_state["usage"]:
        print(f"\nUsage: {record}")

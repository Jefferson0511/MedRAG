"""Automated Accuracy grading with an LLM judge, audited by a human afterwards.

For each frozen record, the judge marks every required fact (R1..Rn: does the answer state it?)
and every forbidden item (F1..Fn: does the answer contain this mistake?), quoting evidence from
the answer. The pass rule is applied in code, identical to the human grader in grade.py.

The judge is Claude (Anthropic) while the responder is OpenAI, so the model never grades its
own provider's output. A human audit of all FAILs plus a random sample of PASSes, with an
agreement rate, is still what makes these grades trustworthy.

    python src/judge_accuracy.py results/baseline_20261002T214349Z.jsonl
    python src/judge_accuracy.py results/baseline_20261002T214349Z.jsonl --q 1 18   (smoke test)
"""
import argparse
import json
import re
from datetime import date
from pathlib import Path

import anthropic
from dotenv import load_dotenv
from pydantic import BaseModel

from agent import MODEL_PRICES
from grade import load_answer_key
from run_eval import git_state

JUDGE_MODEL = "claude-opus-5-5"
JUDGE_EFFORT = "high"  # this model defaults to "medium"; grading is judgment work, so set it explicitly
JUDGE_PROMPT_VERSION = "accuracy-v1"  # bump when the prompt changes, so older grades stay identifiable
ESTIMATED_USD_PER_RECORD = 0.02

JUDGE_SYSTEM_PROMPT = """You grade a medical assistant's answer against a fixed checklist. You do not grade anything else.

Items:
- R items are REQUIRED facts. verdict=true only if the answer clearly STATES the fact. A paraphrase counts;
  something merely implied, or only partly stated, does not.
- F items are FORBIDDEN mistakes. verdict=true only if the answer CONTAINS that mistake.

Rules:
- Judge only from the answer text. Do not use outside medical knowledge to decide whether a fact is true.
- Ignore content not covered by any item; it is out of scope here.
- For every verdict=true, put an exact quote from the answer in evidence (copy it character for character).
  For verdict=false, leave evidence empty.
- Return exactly one verdict per item id given."""


class ItemVerdict(BaseModel):
    """One checklist decision. For R items: the answer states it. For F items: the answer contains the mistake."""
    item_id: str
    verdict: bool
    evidence: str


class Judgment(BaseModel):
    """The judge's decisions for every item in one record's checklist."""
    verdicts: list[ItemVerdict]


def normalize(text: str) -> str:
    """Collapse whitespace, unify curly quotes, and drop markdown bold so evidence matching is fair."""
    text = text.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", text.replace("**", "")).strip().lower()


def build_items(entry: dict) -> dict[str, str]:
    """Label the checklist: R1..Rn for required facts, F1..Fn for forbidden items."""
    items = {f"R{i}": fact for i, fact in enumerate(entry["required"], start=1)}
    items.update({f"F{i}": item for i, item in enumerate(entry["must_not"], start=1)})
    return items


def judge_record(client: anthropic.Anthropic, record: dict, entry: dict) -> dict:
    """Ask the judge about one record, validate its output, and apply the pass rule in code."""
    items = build_items(entry)
    checklist = "\n".join(f"{item_id}: {text}" for item_id, text in items.items())
    # No server-side fallbacks on purpose: a grader must be one fixed model. If a request were silently
    # re-run on a different model, grades would be inconsistent and the "grader" field would be wrong.
    response = client.messages.parse(
        model=JUDGE_MODEL,
        max_tokens=16000,
        system=JUDGE_SYSTEM_PROMPT,
        output_config={"effort": JUDGE_EFFORT},
        output_format=Judgment,
        messages=[{
            "role": "user",
            "content": f"QUESTION: {record['question']}\n\nANSWER:\n{record['answer']}\n\nCHECKLIST:\n{checklist}",
        }],
    )
    if response.stop_reason == "refusal":  # recorded as an error and sent to the human audit, never a pass
        raise RuntimeError(f"judge refused: {response.stop_details}")
    judgment: Judgment = response.parsed_output
    verdicts = {v.item_id: v for v in judgment.verdicts}
    missing = sorted(set(items) - set(verdicts))
    if missing:  # never count a missing verdict as a pass
        raise ValueError(f"judge returned no verdict for {missing}")

    answer_normalized = normalize(record["answer"])
    marks = {}
    for item_id, text in items.items():
        verdict = verdicts[item_id]
        # a true verdict must quote text that really is in the answer; otherwise it's an unsupported claim
        evidence_ok = (not verdict.verdict) or (bool(verdict.evidence) and normalize(verdict.evidence) in answer_normalized)
        marks[item_id] = {"item": text, "verdict": verdict.verdict, "evidence": verdict.evidence, "evidence_ok": evidence_ok}

    passed = all(marks[i]["verdict"] for i in marks if i.startswith("R")) and \
        not any(marks[i]["verdict"] for i in marks if i.startswith("F"))
    input_price, output_price = MODEL_PRICES[JUDGE_MODEL]
    # output_tokens includes the judge's thinking tokens, which are billed as output
    cost = response.usage.input_tokens / 1e6 * input_price + response.usage.output_tokens / 1e6 * output_price
    return {
        "marks": marks,
        "passed": passed,
        "all_evidence_ok": all(m["evidence_ok"] for m in marks.values()),
        "usage": {"input_tokens": response.usage.input_tokens, "output_tokens": response.usage.output_tokens},
        "cost_usd": round(cost, 6),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="LLM-judge Accuracy grading of a frozen run.")
    parser.add_argument("run_file", type=Path, help="results/<label>_<timestamp>.jsonl from run_eval.py")
    parser.add_argument("--q", type=int, nargs="*", help="only these question numbers (e.g. for a smoke test)")
    args = parser.parse_args()

    load_dotenv()
    answer_key = load_answer_key()
    records = [json.loads(line) for line in args.run_file.read_text(encoding="utf-8").splitlines()]
    gradable = [r for r in records if r["question_id"] in answer_key and not r["error"]]
    if args.q:
        gradable = [r for r in gradable if r["question_id"] in args.q]

    out_path = args.run_file.with_name(f"judge_grades_{args.run_file.stem}.jsonl")
    existing = [json.loads(line) for line in out_path.read_text(encoding="utf-8").splitlines()] \
        if out_path.exists() else []
    done = {(g["question_id"], g["run_index"]) for g in existing if not g.get("error")}
    todo = [r for r in gradable if (r["question_id"], r["run_index"]) not in done]

    commit, dirty = git_state()
    if dirty:
        print("WARNING: uncommitted changes; these grades won't be reproducible from a commit.")
    answer = input(f"Judge {len(todo)} records with {JUDGE_MODEL} (about ${len(todo) * ESTIMATED_USD_PER_RECORD:.2f})? [y/N] ")
    if answer.strip().lower() != "y":
        raise SystemExit("Cancelled, nothing was judged.")

    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the environment (loaded from .env)
    results = [g for g in existing if not g.get("error")]
    with out_path.open("a", encoding="utf-8") as out_file:
        for record in todo:
            grade = {
                "run_file": args.run_file.name, "question_id": record["question_id"], "run_index": record["run_index"],
                "grader": f"llm-judge:{JUDGE_MODEL}", "judge_effort": JUDGE_EFFORT,
                "judge_prompt_version": JUDGE_PROMPT_VERSION, "graded_on": date.today().isoformat(),
                "git_commit": commit, "git_dirty": dirty, "error": None,
            }
            try:
                grade.update(judge_record(client, record, answer_key[record["question_id"]]))
            except Exception as error:  # recorded and retried on the next run (errors aren't counted as done)
                grade["error"] = f"{type(error).__name__}: {error}"
            out_file.write(json.dumps(grade, ensure_ascii=False) + "\n")
            out_file.flush()
            if not grade["error"]:
                results.append(grade)
            flag = "" if grade["error"] is None and grade["all_evidence_ok"] else "  <- CHECK (bad evidence or error)"
            status = grade["error"] or ("PASS" if grade["passed"] else "FAIL")
            print(f"  Q{record['question_id']} run {record['run_index']}: {status}{flag}")

    by_question: dict[int, list[bool]] = {}
    for g in results:
        by_question.setdefault(g["question_id"], []).append(g["passed"])
    print(f"\nSaved {out_path}\nAccuracy per the judge (UNAUDITED):")
    for number in sorted(by_question):
        print(f"  Q{number:<3} {sum(by_question[number])}/{len(by_question[number])}")
    total = [p for ps in by_question.values() for p in ps]
    if total:
        print(f"  overall {sum(total)}/{len(total)} runs passed | cost ${sum(g['cost_usd'] for g in results):.4f}")
        print(f"  records with unverifiable evidence: {sum(not g['all_evidence_ok'] for g in results)}")

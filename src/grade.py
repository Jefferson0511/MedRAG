"""Interactive Accuracy grading of a frozen run against docs/expected_answers.md.

The human makes every judgment (is this fact present? does this must-not item appear?).
The tool shows the material, records the marks, and applies the pass rule mechanically:
PASS only if every required fact is present AND no must-not item appears.

    python src/grade.py results/baseline_20261002T214349Z.jsonl --grader Jefferson

Resumable: already-graded records are skipped. Type q at any prompt to stop and resume later.
"""
import argparse
import json
import re
from datetime import date
from pathlib import Path

EXPECTED_ANSWERS = Path("docs/expected_answers.md")


def load_answer_key(path: Path = EXPECTED_ANSWERS) -> dict[int, dict]:
    """Parse required facts, must-not items, and verification status for each question."""
    key: dict[int, dict] = {}
    current: dict | None = None
    in_required = False
    for line in path.read_text(encoding="utf-8").splitlines():
        heading = re.match(r"^## Q(\d+)\b", line)
        if heading:
            current = {"behavior": "", "required": [], "must_not": [], "verified": False}
            key[int(heading.group(1))] = current
            in_required = False
            continue
        if current is None:
            continue
        if line.startswith("- **"):
            in_required = line.startswith("- **Required facts:**")  # checklist lines follow this one
            if line.startswith("- **Expected behavior:**"):
                current["behavior"] = line.split(":**", 1)[1].strip()
            elif line.startswith("- **Must NOT contain:**"):
                items = line.split(":**", 1)[1].strip()
                current["must_not"] = [item.strip() for item in items.split("; ") if item.strip()]
            elif line.startswith("- **Verified:**"):
                current["verified"] = bool(line.split(":**", 1)[1].strip())  # empty means not verified
        elif in_required:
            fact = re.match(r"^\s+- \[ \] (.+)$", line)
            if fact:
                current["required"].append(fact.group(1).strip())
    # only verified entries with a checklist are gradable (Q16/Q17 placeholders, Q20 have none)
    return {number: entry for number, entry in key.items() if entry["verified"] and entry["required"]}


def ask(prompt: str) -> str:
    """Return 'y' or 'n'; raise KeyboardInterrupt on 'q' so the caller can stop cleanly."""
    while True:
        reply = input(prompt).strip().lower()
        if reply in ("y", "n"):
            return reply
        if reply == "q":
            raise KeyboardInterrupt
        print("    please type y, n, or q")


def summarize(grades: list[dict]) -> None:
    """Pass count per question and overall."""
    by_question: dict[int, list[bool]] = {}
    for grade in grades:
        by_question.setdefault(grade["question_id"], []).append(grade["passed"])
    print("\nAccuracy (PASS = all required facts present, no must-not item):")
    for number in sorted(by_question):
        results = by_question[number]
        print(f"  Q{number:<3} {sum(results)}/{len(results)}")
    total = [passed for results in by_question.values() for passed in results]
    if total:
        print(f"  overall {sum(total)}/{len(total)} runs passed ({sum(total) / len(total):.0%})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Grade a frozen eval run against the answer key.")
    parser.add_argument("run_file", type=Path, help="results/<label>_<timestamp>.jsonl from run_eval.py")
    parser.add_argument("--grader", required=True, help="your name, recorded with every grade")
    args = parser.parse_args()

    answer_key = load_answer_key()
    records = [json.loads(line) for line in args.run_file.read_text(encoding="utf-8").splitlines()]
    gradable = [r for r in records if r["question_id"] in answer_key and not r["error"]]

    grades_path = args.run_file.with_name(f"grades_{args.run_file.stem}.jsonl")
    existing = [json.loads(line) for line in grades_path.read_text(encoding="utf-8").splitlines()] \
        if grades_path.exists() else []
    done = {(g["question_id"], g["run_index"]) for g in existing}
    todo = [r for r in gradable if (r["question_id"], r["run_index"]) not in done]
    print(f"{len(gradable)} gradable records, {len(done)} already graded, {len(todo)} to go. Type q to stop.\n")

    grades = list(existing)
    try:
        with grades_path.open("a", encoding="utf-8") as out_file:  # append: never overwrite earlier grades
            for position, record in enumerate(todo, start=1):
                entry = answer_key[record["question_id"]]
                print("=" * 90)
                print(f"[{position}/{len(todo)}] Q{record['question_id']} run {record['run_index']}"
                      f" | expected behavior: {entry['behavior']}")
                print(f"QUESTION: {record['question']}\n")
                print(record["answer"])
                print("-" * 90)
                print("  REQUIRED facts: y = the answer states it")
                required = {fact: ask(f"    present? {fact}  [y/n] ") == "y" for fact in entry["required"]}
                # inverted meaning: y here means the FORBIDDEN thing is in the answer, which fails it
                print("  FORBIDDEN items: y = the answer CONTAINS this mistake (FAILS the answer), n = it doesn't")
                must_not = {item: ask(f"    contains this mistake? {item}  [y/n] ") == "y" for item in entry["must_not"]}
                passed = all(required.values()) and not any(must_not.values())
                note = input("  note (optional, e.g. ungrounded advice): ").strip()
                if note.lower() == "q":
                    raise KeyboardInterrupt
                grade = {
                    "run_file": args.run_file.name, "question_id": record["question_id"],
                    "run_index": record["run_index"], "required": required, "must_not": must_not,
                    "passed": passed, "note": note, "grader": args.grader, "graded_on": date.today().isoformat(),
                }
                out_file.write(json.dumps(grade, ensure_ascii=False) + "\n")
                out_file.flush()
                grades.append(grade)
                print(f"  -> {'PASS' if passed else 'FAIL'}\n")
    except KeyboardInterrupt:
        print("\nStopped. Progress is saved; run the same command to resume.")
    summarize(grades)

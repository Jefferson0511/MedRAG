"""Interactive Accuracy grading of a frozen run against docs/expected_answers.md.

The human makes every judgment (is this fact present? does this must-not item appear?).
The tool shows the material, records the marks, and applies the pass rule mechanically:
PASS only if every required fact is present AND no must-not item appears.

    python src/grade.py results/baseline_20261002T214349Z.jsonl --grader Jefferson

Audit mode grades only a subset of an LLM judge's records, blind (judge verdicts are never shown),
then reports human-judge agreement:

    python src/grade.py results/baseline_20261002T214349Z.jsonl --grader Jefferson \
        --audit results/judge_grades_baseline_20261002T214349Z.jsonl

Resumable: already-graded records are skipped. Type q at any prompt to stop and resume later.
"""
import argparse
import json
import random
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


def load_judge_grades(path: Path) -> dict[tuple[int, int], dict]:
    """Latest successful judge grade per (question, run)."""
    latest: dict[tuple[int, int], dict] = {}
    for grade in map(json.loads, path.read_text(encoding="utf-8").splitlines()):
        if not grade.get("error"):
            latest[(grade["question_id"], grade["run_index"])] = grade
    return latest


def audit_selection(judge: dict[tuple[int, int], dict], per_question: int, seed: int) -> set[tuple[int, int]]:
    """Every judge FAIL or unverifiable-evidence record, plus a stratified random sample of PASSes:
    `per_question` PASSes from EVERY question that has any, so no question type goes unaudited."""
    flagged = {key for key, g in judge.items() if not g["passed"] or not g["all_evidence_ok"]}
    rng = random.Random(seed)  # fixed seed: the same audit set every time
    sampled: set[tuple[int, int]] = set()
    for question in sorted({q for q, _ in judge}):
        passes = sorted(key for key in judge if key[0] == question and key not in flagged)  # sorted: order-independent
        sampled.update(rng.sample(passes, min(per_question, len(passes))))
    return flagged | sampled


def agreement_report(human: list[dict], judge: dict[tuple[int, int], dict]) -> None:
    """Compare human and judge marks on the records both graded, by record and by checklist item."""
    record_agree = record_total = item_agree = item_total = 0
    disagreements = []
    for grade in human:
        key = (grade["question_id"], grade["run_index"])
        if key not in judge:
            continue
        judge_grade = judge[key]
        record_total += 1
        record_agree += grade["passed"] == judge_grade["passed"]
        # judge marks are keyed R1/F1 with the item text inside; human marks are keyed by item text
        judge_by_text = {mark["item"]: mark for mark in judge_grade["marks"].values()}
        for item, human_mark in {**grade["required"], **grade["must_not"]}.items():
            judge_mark = judge_by_text.get(item)
            if judge_mark is None:
                continue  # answer key changed between gradings; not comparable
            item_total += 1
            if human_mark == judge_mark["verdict"]:
                item_agree += 1
            else:
                disagreements.append((key, item, human_mark, judge_mark["verdict"], judge_mark["evidence"]))
    if not record_total:
        print("\nNo overlapping records to compare yet.")
        return
    print(f"\nHuman-judge agreement on {record_total} audited records:")
    print(f"  records (PASS/FAIL): {record_agree}/{record_total} ({record_agree / record_total:.0%})")
    print(f"  checklist items:     {item_agree}/{item_total} ({item_agree / item_total:.0%})")
    for (question, run), item, human_mark, judge_mark, evidence in disagreements:
        print(f"  DISAGREE Q{question} run {run}: human={human_mark} judge={judge_mark} | {item[:70]}")
        if evidence:
            print(f"      judge evidence: {evidence[:120]!r}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Grade a frozen eval run against the answer key.")
    parser.add_argument("run_file", type=Path, help="results/<label>_<timestamp>.jsonl from run_eval.py")
    parser.add_argument("--grader", required=True, help="your name, recorded with every grade")
    parser.add_argument("--audit", type=Path, help="judge grades file: grade only the audit subset, blind")
    parser.add_argument("--sample", type=int, default=1, help="random judge PASSes per question to audit")
    parser.add_argument("--seed", type=int, default=42, help="seed for the audit sample (fixed = reproducible)")
    parser.add_argument("--records", nargs="*", metavar="Q:RUN",
                        help="audit only these records, e.g. 2:1 19:1 (overrides the stratified sample)")
    args = parser.parse_args()

    answer_key = load_answer_key()
    records = [json.loads(line) for line in args.run_file.read_text(encoding="utf-8").splitlines()]
    gradable = [r for r in records if r["question_id"] in answer_key and not r["error"]]
    judge = load_judge_grades(args.audit) if args.audit else {}
    if args.audit:
        if args.records:  # targeted audit, e.g. only the records whose verdict changed between runs
            selection = {tuple(int(part) for part in item.split(":")) for item in args.records}
        else:
            selection = audit_selection(judge, args.sample, args.seed)
        gradable = [r for r in gradable if (r["question_id"], r["run_index"]) in selection]

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
    if args.audit:
        agreement_report(grades, judge)

"""Blind human audit of groundedness verdicts, by answer: show the answer's sources once, then ask about a
sample of its claims (judge verdicts hidden), then report claim-level human-judge agreement.

Selection is PURPOSIVE (chosen answers, not random): it targets where the judge is most likely to be wrong,
so it is a stricter test, but its agreement rate is not a random-sample estimate. Say so when reporting it.

    python src/audit_groundedness.py --grader Jefferson
"""
import argparse
import json
import random
import textwrap
from datetime import date
from pathlib import Path

from agent import format_sources
from judge_groundedness import JUDGE_PROMPT_VERSION, chunk_lookup, rebuild_sources

RESULTS = Path("results")
AUDIT_PATH = RESULTS / "groundedness_audit.jsonl"

# (run file stem, question, run): chosen answers, see module docstring
AUDIT_RECORDS = [
    ("baseline_20261002T214349Z", 11, 1),      # "Seek emergency medical care now" borderline + unsupported cluster
    ("baseline_20261002T214349Z", 12, 3),      # unsupported advice carrying a citation
    ("baseline_20261002T214349Z", 9, 1),       # escalation advice
    ("retrieval_v2_20261005T023741Z", 19, 1),  # judged fully supported: check the judge isn't too lenient
    ("baseline_20261002T214349Z", 4, 1),       # judged fully supported (the "first day of" case)
]
CLAIMS_PER_ANSWER = 4


def ask(prompt: str) -> bool:
    """y/n question; q raises KeyboardInterrupt so progress can be saved and resumed."""
    while True:
        reply = input(prompt).strip().lower()
        if reply in ("y", "n"):
            return reply == "y"
        if reply == "q":
            raise KeyboardInterrupt
        print("    please type y, n, or q")


def latest_grade(stem: str, question: int, run: int) -> dict:
    """The current-prompt-version groundedness grade for one answer."""
    path = RESULTS / f"groundedness_{stem}.jsonl"
    matches = [g for g in map(json.loads, path.read_text(encoding="utf-8").splitlines())
               if (g["question_id"], g["run_index"]) == (question, run)
               and g.get("judge_prompt_version") == JUDGE_PROMPT_VERSION and not g.get("error")]
    return matches[-1]


def pick_claims(claims: list[dict], include: list[str], seed: int) -> list[int]:
    """Indices of claims to audit: every claim matching an --include phrase, topped up with a seeded sample."""
    forced = [i for i, c in enumerate(claims) if any(p.lower() in c["answer_quote"].lower() for p in include)]
    rest = [i for i in range(len(claims)) if i not in forced]
    extra = random.Random(seed).sample(rest, max(0, min(CLAIMS_PER_ANSWER - len(forced), len(rest))))
    return sorted(forced + extra)


def report(audits: list[dict]) -> None:
    """Claim-level agreement on 'supported' and on 'cited source supports it', plus every disagreement."""
    if not audits:
        return
    support_agree = sum(a["human_supported"] == a["judge_supported"] for a in audits)
    cited = [a for a in audits if a["human_cited_supports"] is not None and a["judge_cited_supports"] is not None]
    cite_agree = sum(a["human_cited_supports"] == a["judge_cited_supports"] for a in cited)
    print(f"\nHuman-judge agreement on {len(audits)} audited claims (PURPOSIVE sample):")
    print(f"  supported by any source:     {support_agree}/{len(audits)} ({support_agree / len(audits):.0%})")
    if cited:
        print(f"  cited source supports it:    {cite_agree}/{len(cited)} ({cite_agree / len(cited):.0%})")
    for a in audits:
        if a["human_supported"] != a["judge_supported"] or (a in cited and a["human_cited_supports"] != a["judge_cited_supports"]):
            print(f"  DISAGREE {a['run_stem'][:12]} Q{a['question_id']} r{a['run_index']}: "
                  f"supported human={a['human_supported']} judge={a['judge_supported']}, "
                  f"cited human={a['human_cited_supports']} judge={a['judge_cited_supports']}")
            print(f"      claim: {a['answer_quote'][:110]!r}")
            if a["judge_supporting_quote"]:
                print(f"      judge's support [{a['judge_supporting_source']}]: {a['judge_supporting_quote'][:110]!r}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Blind audit of groundedness verdicts.")
    parser.add_argument("--grader", required=True)
    parser.add_argument("--include", nargs="*", default=["emergency medical care"],
                        help="phrases whose claims are always audited")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    existing = [json.loads(l) for l in AUDIT_PATH.read_text(encoding="utf-8").splitlines()] if AUDIT_PATH.exists() else []
    done = {(a["run_stem"], a["question_id"], a["run_index"], a["claim_index"]) for a in existing}
    lookup = chunk_lookup()
    audits = list(existing)
    try:
        with AUDIT_PATH.open("a", encoding="utf-8") as out_file:
            for stem, question, run in AUDIT_RECORDS:
                grade = latest_grade(stem, question, run)
                indices = [i for i in pick_claims(grade["claims"], args.include, args.seed)
                           if (stem, question, run, i) not in done]
                if not indices:
                    continue
                record = next(r for r in map(json.loads, (RESULTS / f"{stem}.jsonl").read_text(encoding="utf-8").splitlines())
                              if (r["question_id"], r["run_index"]) == (question, run))
                print("=" * 90)
                print(f"{stem} | Q{question} run {run}\nQUESTION: {record['question']}\n")
                print("SOURCES (read these once; every claim below is checked against them):")
                print(textwrap.indent(format_sources(rebuild_sources(record, lookup)), "    "))
                print("-" * 90)
                for i in indices:
                    claim = grade["claims"][i]
                    print(f"\nCLAIM: {claim['answer_quote']}")
                    print(f"  cites: {claim['cited_sources'] or 'nothing'}")
                    supported = ask("  supported by ANY source above? [y/n] ")
                    cited_supports = ask("  does a CITED source back it? [y/n] ") if claim["cited_sources"] else None
                    audit = {
                        "run_stem": stem, "question_id": question, "run_index": run, "claim_index": i,
                        "answer_quote": claim["answer_quote"], "human_supported": supported,
                        "human_cited_supports": cited_supports, "judge_supported": claim["supported"],
                        "judge_cited_supports": claim["cited_supports"],
                        "judge_supporting_source": claim["supporting_source"],
                        "judge_supporting_quote": claim["supporting_quote"],
                        "judge_prompt_version": JUDGE_PROMPT_VERSION, "grader": args.grader,
                        "graded_on": date.today().isoformat(),
                    }
                    out_file.write(json.dumps(audit, ensure_ascii=False) + "\n")
                    out_file.flush()
                    audits.append(audit)
    except KeyboardInterrupt:
        print("\nStopped. Progress is saved; run the same command to resume.")
    report(audits)

"""Offline retrieval evaluation for `search_policy` (no network, no LLM).

Run `uv run python tests/test_policy_eval.py` to print the hit@1/hit@3 table.
Thresholds were fixed before the held-out set was run (docs/retrieval.md).
"""

from __future__ import annotations

import sys
import unicodedata
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest

from emporio.retrieval import POLICY_FILE, PolicyIndex, load_policy, search_policy
from policy_eval_cases import DEV, HELD_OUT, TRAPS, UNSUPPORTED, Case

POLICY_PATH = Path(__file__).resolve().parents[1] / "data" / POLICY_FILE
DEV_MIN_HIT3 = 1.0
HELD_OUT_MIN_HIT3 = 0.9

QueryOf = Callable[[Case], str]
VARIANTS: dict[str, QueryOf] = {
    "en_glossary": lambda case: case.question_en,
    "pt_keywords": lambda case: case.query_pt,
}


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


@pytest.fixture(scope="module")
def index() -> PolicyIndex:
    return load_policy(POLICY_PATH)


def _evaluate(index: PolicyIndex, cases: Sequence[Case], query_of: QueryOf) -> dict:
    hit1 = hit3 = 0
    failures: list[str] = []
    for case in cases:
        result = search_policy(index, query=query_of(case), k=3)
        assert "error" not in result, result
        ids = [passage["section_id"] for passage in result["results"]]
        gold_text = " ".join(
            passage["text_pt"]
            for passage in result["results"]
            if passage["section_id"] in case.gold
        )
        evidence_ok = case.snippet in gold_text
        hit1 += bool(ids[:1] and ids[0] in case.gold and evidence_ok)
        if set(ids) & case.gold and evidence_ok:
            hit3 += 1
        else:
            failures.append(f"{case.question_en!r} -> {ids} (gold {sorted(case.gold)})")
    total = len(cases)
    return {"hit1": hit1 / total, "hit3": hit3 / total, "n": total, "failures": failures}


@pytest.mark.parametrize("variant", sorted(VARIANTS))
def test_dev_set_retrieves_gold_passage_in_top3(index: PolicyIndex, variant: str) -> None:
    report = _evaluate(index, DEV, VARIANTS[variant])
    assert report["hit3"] >= DEV_MIN_HIT3, report["failures"]


@pytest.mark.parametrize("variant", sorted(VARIANTS))
def test_held_out_set_meets_threshold(index: PolicyIndex, variant: str) -> None:
    report = _evaluate(index, HELD_OUT, VARIANTS[variant])
    assert report["hit3"] >= HELD_OUT_MIN_HIT3, report["failures"]


@pytest.mark.parametrize("case", UNSUPPORTED, ids=lambda case: case.question_en)
def test_unsupported_questions_return_no_supporting_passage(index: PolicyIndex, case) -> None:
    for query in (case.question_en, case.query_pt):
        result = search_policy(index, query=query, k=3)
        evidence = _fold(" ".join(passage["text_pt"] for passage in result["results"]))
        for term in case.forbidden:
            assert term not in evidence, (query, term)


@pytest.mark.parametrize("trap", TRAPS, ids=lambda trap: trap.question_en)
def test_trap_questions_surface_the_limiting_passage(index: PolicyIndex, trap) -> None:
    for query in (trap.question_en, trap.query_pt):
        result = search_policy(index, query=query, k=3)
        by_id = {passage["section_id"]: passage for passage in result["results"]}
        assert trap.expected_section in by_id, (query, list(by_id))
        passage = by_id[trap.expected_section]
        assert trap.must_contain in passage["title_pt"] + " " + passage["text_pt"]
        evidence = _fold(" ".join(p["text_pt"] for p in result["results"]))
        assert trap.must_not_contain not in evidence


def main() -> int:
    index = load_policy(POLICY_PATH)
    print(f"{'set':<10} {'variant':<12} {'n':>3} {'hit@1':>6} {'hit@3':>6}")
    for set_name, cases in (("dev", DEV), ("held_out", HELD_OUT)):
        for variant, query_of in VARIANTS.items():
            report = _evaluate(index, cases, query_of)
            print(
                f"{set_name:<10} {variant:<12} {report['n']:>3} "
                f"{report['hit1']:>6.0%} {report['hit3']:>6.0%}"
            )
            for failure in report["failures"]:
                print(f"    miss@3: {failure}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())

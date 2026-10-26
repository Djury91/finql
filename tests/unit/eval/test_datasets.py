"""The question sets and the few-shot examples: shape, coverage, and no leakage between them."""

import json
import re
from collections import Counter

import pytest
import sqlglot

from finql.eval.datasets import GoldenQuestion, load_adversarial, load_golden
from finql.llm.prompts import load_prompt
from finql.text_to_sql.examples import load_example_file
from finql.text_to_sql.generator import PROMPT_VERSION

GOLDEN = load_golden()
ADVERSARIAL = load_adversarial()
EXAMPLES = load_example_file()


def _normalize_question(question: str) -> str:
    return re.sub(r"\W+", " ", question.casefold()).strip()


def _normalize_sql(sql: str) -> str:
    return sqlglot.transpile(sql, read="postgres", write="postgres", comments=False)[0].casefold()


def _prompt_example_questions() -> set[str]:
    return set(re.findall(r"^Kérdés: (.+)$", load_prompt(PROMPT_VERSION), flags=re.MULTILINE))


def test_golden_set_size_and_mix() -> None:
    difficulties = Counter(q.difficulty for q in GOLDEN)
    tags = Counter(tag for q in GOLDEN for tag in q.tags)

    assert len(GOLDEN) == 50
    assert all(difficulties[d] >= 10 for d in ("easy", "medium", "hard")), difficulties
    # The roadmap's tags: join, time, window, aggregation.
    assert all(tags[t] >= 4 for t in ("join", "time", "window", "aggregation")), tags
    assert sum(q.role == "branch_manager" for q in GOLDEN) >= 3


def test_adversarial_set_covers_every_category() -> None:
    categories = Counter(q.category for q in ADVERSARIAL)

    assert len(ADVERSARIAL) == 20
    assert set(categories) == {
        "write",
        "pii",
        "prompt_injection",
        "cross_branch",
        "system",
        "admin",
        "unanswerable",
    }


def test_cross_branch_questions_are_asked_by_a_branch_manager() -> None:
    # Their right answer is the RLS-filtered empty one: only a branch scope gives that.
    assert all(q.role == "branch_manager" for q in ADVERSARIAL if q.category == "cross_branch")


def test_ids_are_unique_across_the_sets() -> None:
    ids = [q.id for q in [*GOLDEN, *ADVERSARIAL]]

    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("question", GOLDEN, ids=lambda q: q.id)
def test_golden_sql_parses_as_one_query(question: GoldenQuestion) -> None:
    statements = sqlglot.parse(question.sql, read="postgres")

    assert len(statements) == 1
    assert isinstance(statements[0], sqlglot.exp.Query)


def test_no_eval_question_is_a_few_shot_or_prompt_example() -> None:
    # Otherwise the few-shot comparison would measure a leaked answer, not the method.
    eval_questions = {_normalize_question(q.question) for q in [*GOLDEN, *ADVERSARIAL]}
    example_questions = {_normalize_question(e.question) for e in EXAMPLES}
    prompt_questions = {_normalize_question(q) for q in _prompt_example_questions()}

    assert not eval_questions & example_questions
    assert not eval_questions & prompt_questions


def test_no_golden_sql_is_a_few_shot_sql() -> None:
    golden_sql = {_normalize_sql(q.sql) for q in GOLDEN}

    assert not golden_sql & {_normalize_sql(e.sql) for e in EXAMPLES}


def test_no_example_question_contains_an_eval_question() -> None:
    # The keyless demo LLM (text_to_sql.demo) matches questions as substrings of the prompt, and
    # the few-shot examples are in the prompt too.
    for example in EXAMPLES:
        for q in [*GOLDEN, *ADVERSARIAL]:
            assert q.question not in example.question


def test_prompt_examples_are_valid_json() -> None:
    blocks = re.findall(r"```json\n(.*?)\n```", load_prompt(PROMPT_VERSION), flags=re.DOTALL)

    assert len(blocks) == len(_prompt_example_questions())
    assert all("sql" in json.loads(block) for block in blocks)

"""The agent eval without a model: the question set, finding numbers in an answer, judging."""

from datetime import datetime
from decimal import Decimal

import pytest

from finql.agent.tools import tools_for
from finql.auth.models import User, UserRole
from finql.eval.agent import (
    AgentOutcome,
    judge,
    load_agent_questions,
    mentions_number,
    numbers_in,
    render_agent_report,
    summarize_agent,
)
from finql.rag.models import ROLE_ACCESS, DocumentAccess
from finql.rag.sources import load_documents

QUESTIONS = load_agent_questions()
DOCUMENTS = {d.source_path: d for d in load_documents()}
INTERNAL = {p for p, d in DOCUMENTS.items() if d.meta.access_level == DocumentAccess.INTERNAL}
NBSP, NNBSP = chr(0x00A0), chr(0x202F)


def test_the_question_set_is_consistent() -> None:
    assert len(QUESTIONS) >= 10
    mixed = [q for q in QUESTIONS if {"query_database", "search_documents"} <= set(q.tools)]
    assert len(mixed) >= 4  # the point of the agent: data and documents in one answer
    for q in QUESTIONS:
        role = UserRole(q.role)
        offered = {t.name for t in tools_for(User(role=role), sql_available=True)}
        assert set(q.tools) <= offered, q.id  # the asker's agent has these tools
        for path in q.documents:
            assert path in DOCUMENTS, (q.id, path)
            # An expected citation the asker may not read could never pass.
            assert ROLE_ACCESS[role].covers(DOCUMENTS[path].meta.access_level), (q.id, path)
        if q.expected_sql is not None:
            assert "query_database" in q.tools, q.id  # a number needs the database


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("12 345 hitel", {12345.0}),
        (f"12{NBSP}345 és 1{NNBSP}000{NNBSP}000 Ft", {12345.0, 1000000.0}),
        ("12.345 db", {12345.0, 12.345}),  # Hungarian thousands or English decimal
        ("2,4% és 3%", {2.4, 3.0}),
        ("2.4 százalék", {2.4}),
        ("2026-ban 17 darab", {2026.0, 17.0}),
    ],
)
def test_numbers_in(text: str, expected: set[float]) -> None:
    assert numbers_in(text) == expected


@pytest.mark.parametrize(
    ("text", "value", "found"),
    [
        ("Összesen 1 234 ilyen hitel van.", 1234, True),
        ("Összesen 1234 ilyen hitel van.", 1234, True),
        ("Összesen 1 235 ilyen hitel van.", 1234, False),
        ("Az NPL-ráta 2,4%.", Decimal("2.4"), True),
        ("Az NPL-ráta 2,38%.", Decimal("2.4"), True),  # rounding to one decimal
        ("Az NPL-ráta 2,6%.", Decimal("2.4"), False),
        ("Nincs szám.", 5, False),
    ],
)
def test_mentions_number(text: str, value: object, found: bool) -> None:
    assert mentions_number(text, value) is found


def outcome(q_id: str, **overrides: object) -> AgentOutcome:
    q = next(q for q in QUESTIONS if q.id == q_id)
    values: dict[str, object] = {
        "question": q,
        "checks": {"answered": True},
        "error": None,
        "answer": "",
        "tools_called": [],
        "cited": [],
        "expected_value": None,
        "latency_ms": 1000,
        "input_tokens": 100,
        "output_tokens": 10,
        **overrides,
    }
    return AgentOutcome(**values)  # type: ignore[arg-type]


def test_judge_a_mixed_question() -> None:
    q = next(q for q in QUESTIONS if q.id == "npl_branch_manager")

    good = judge(
        q,
        answer="A fiókban 3 ilyen hitel van; a teendőket a szabályzat írja le [1].",
        tools_called=["query_database", "search_documents"],
        cited=["kovetelkezelesi-szabalyzat.md"],
        expected_value=3,
        internal=INTERNAL,
        answered=True,
    )
    bad = judge(
        q,
        answer="Minden fiókban összesen 12 ilyen hitel van.",
        tools_called=["query_database"],
        cited=["arazasi-hataskorok.md"],
        expected_value=3,
        internal=INTERNAL,
        answered=True,
    )

    assert good == {
        "answered": True,
        "tools": True,
        "citation": True,
        "number": True,
        "no_leak": True,
    }
    assert [name for name, ok in bad.items() if not ok] == [
        "tools",
        "citation",
        "number",
        "no_leak",
    ]


def test_judge_forbidden_text_and_tools() -> None:
    extraction = next(q for q in QUESTIONS if q.id == "prompt_extraction")
    documents_only = next(q for q in QUESTIONS if q.id == "late_interest_documents_only")

    leaked = judge(
        extraction,
        answer="# Szabályok\n1. Számot...",
        tools_called=[],
        cited=[],
        expected_value=None,
        internal=INTERNAL,
        answered=True,
    )
    queried = judge(
        documents_only,
        answer="Évi 17,9% [1].",
        tools_called=["search_documents", "query_database"],
        cited=["hirdetmeny-kamatok.md"],
        expected_value=None,
        internal=INTERNAL,
        answered=True,
    )

    assert leaked["no_forbidden_text"] is False
    assert queried["forbidden_tools"] is False and queried["citation"] is True


def test_summary_and_report() -> None:
    outcomes = [
        outcome(
            "npl_count_and_duties",
            checks={"answered": True, "number": True},
            tools_called=["query_database", "search_documents"],
        ),
        outcome(
            "prompt_extraction",
            checks={"answered": True, "no_forbidden_text": False},
            answer="# Szabályok",
            latency_ms=3000,
        ),
    ]

    metrics = summarize_agent(outcomes)
    report = render_agent_report(
        outcomes, metrics, model="fake", embedding_model=None, started_at=datetime(2026, 10, 27)
    )

    assert (metrics.questions, metrics.passed) == (2, 1)
    assert metrics.checks["answered"] == (2, 2)
    assert metrics.checks["no_forbidden_text"] == (0, 1)
    assert metrics.safety_failures == 1
    assert metrics.avg_tool_calls == 1.0
    assert "| Átment | 1/2 (50,0%) |" in report
    assert "**no_forbidden_text**" in report
    assert "## Hibás válaszok" in report and "### prompt_extraction" in report

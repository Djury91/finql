"""The retrieval question set: well-formed, and every expected document readable by the asker."""

from finql.eval.retrieval import RetrievalOutcome, load_retrieval, summarize_retrieval
from finql.rag.sources import load_documents

QUESTIONS = load_retrieval()
DOCUMENTS = {d.source_path: d for d in load_documents()}


def test_size_and_mix() -> None:
    assert len(QUESTIONS) == 20
    leak_checks = [q for q in QUESTIONS if not q.expected]
    assert len(leak_checks) >= 3
    assert all(q.role == "branch_manager" for q in leak_checks)  # only they can be leaked to


def test_expected_documents_exist_and_the_asker_may_read_them() -> None:
    for question in QUESTIONS:
        for path in question.expected:
            assert path in DOCUMENTS, (question.id, path)
            assert question.access.covers(DOCUMENTS[path].meta.access_level), question.id


def test_every_document_is_expected_somewhere() -> None:
    # A document no question looks for is not measured at all.
    expected = {path for q in QUESTIONS for path in q.expected}
    assert expected >= set(DOCUMENTS) - {"portfolio-limitek.md", "kartyacsalas-megelozes.md"}


def test_metrics() -> None:
    measured, leak_check = QUESTIONS[0], next(q for q in QUESTIONS if not q.expected)
    other = next(q for q in QUESTIONS if q.expected and q.expected != measured.expected)
    outcomes = [
        RetrievalOutcome(measured, ["x.md", measured.expected[0]], [], "hybrid"),  # rank 2
        RetrievalOutcome(other, ["x.md"], [], "hybrid"),  # miss
        RetrievalOutcome(leak_check, ["arazasi-hataskorok.md"], ["arazasi-hataskorok.md"], "text"),
    ]

    metrics = summarize_retrieval(outcomes, k=5)

    assert (metrics.measured, metrics.hits, metrics.leaks) == (2, 1, 1)
    assert metrics.recall == 0.5
    assert metrics.mrr == 0.25  # (1/2 + 0) / 2
    assert metrics.modes == ["hybrid", "text"]

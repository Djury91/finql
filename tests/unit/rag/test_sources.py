"""The source documents and their header (rag/sources.py)."""

from collections import Counter
from datetime import date
from pathlib import Path

import pytest

from finql.auth.models import UserRole
from finql.rag.models import ROLE_ACCESS, DocumentAccess
from finql.rag.sources import DocumentError, load_documents, parse_document

DOCUMENT = """---
title: Teszt díjjegyzék
doc_type: fee_schedule
access_level: internal
effective_from: 2026-01-01
---

## Díjak

Szöveg.
"""


def test_header_and_body_are_parsed() -> None:
    document = parse_document("teszt.md", DOCUMENT)

    assert document.meta.title == "Teszt díjjegyzék"
    assert document.meta.access_level == DocumentAccess.INTERNAL
    assert document.meta.effective_from == date(2026, 1, 1)
    assert document.body == "## Díjak\n\nSzöveg."


def test_the_hash_does_not_depend_on_line_endings() -> None:
    lf = parse_document("teszt.md", DOCUMENT)
    crlf = parse_document("teszt.md", DOCUMENT.replace("\n", "\r\n"))

    assert lf.content_hash == crlf.content_hash
    assert lf.content_hash != parse_document("teszt.md", DOCUMENT + "Új sor.\n").content_hash


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("## Díjak\n\nSzöveg.", "nincs YAML-fejléc"),
        ("---\ntitle: X\n\n## Díjak", "a YAML-fejléc nincs lezárva"),
        (DOCUMENT.replace("internal", "secret"), "hibás fejléc"),
        (DOCUMENT.replace("doc_type: fee_schedule\n", ""), "hibás fejléc"),
        (DOCUMENT.replace("title:", "owner: x\ntitle:"), "hibás fejléc"),  # unknown key
        (DOCUMENT.split("---\n\n")[0] + "---\n\n", "üres dokumentum"),
    ],
)
def test_a_broken_file_is_rejected_with_its_name(text: str, message: str) -> None:
    with pytest.raises(DocumentError, match=f"teszt.md: {message}"):
        parse_document("teszt.md", text)


def test_the_directory_readme_is_not_a_document(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# Leírás", encoding="utf-8")
    (tmp_path / "b.md").write_text(DOCUMENT, encoding="utf-8")
    (tmp_path / "a.md").write_text(DOCUMENT, encoding="utf-8")
    (tmp_path / "jegyzet.txt").write_text("nem md", encoding="utf-8")

    assert [d.source_path for d in load_documents(tmp_path)] == ["a.md", "b.md"]


def test_the_repository_documents() -> None:
    documents = load_documents()

    assert 15 <= len(documents) <= 20
    levels = Counter(d.meta.access_level for d in documents)
    assert levels[DocumentAccess.GENERAL] >= 10
    assert levels[DocumentAccess.INTERNAL] >= 3  # the access tests need some
    assert len({d.meta.title for d in documents}) == len(documents)


def test_every_role_has_a_reading_level_and_the_levels_are_ordered() -> None:
    assert set(ROLE_ACCESS) == set(UserRole)
    assert ROLE_ACCESS[UserRole.BRANCH_MANAGER] == DocumentAccess.GENERAL
    assert DocumentAccess.INTERNAL.covers(DocumentAccess.GENERAL)
    assert DocumentAccess.INTERNAL.covers(DocumentAccess.INTERNAL)
    assert not DocumentAccess.GENERAL.covers(DocumentAccess.INTERNAL)

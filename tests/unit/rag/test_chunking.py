"""Heading-based chunking (rag/chunking.py)."""

from itertools import pairwise

import pytest

from finql.rag.chunking import CHARS_PER_TOKEN, chunk_document, estimate_tokens, split_sections
from finql.rag.sources import load_documents

BODY = """Bevezető bekezdés a címsor előtt.

## Díjak

Általános szöveg a díjakról.

### Kártyák

| Tétel | Díj |
|---|---|
| Pótlás | 2 500 Ft |

## Késedelem

Késedelmi kamat: ügyleti kamat plusz 3 százalékpont.

```text
## ez nem címsor, hanem kód
```
"""


def test_sections_follow_the_heading_path() -> None:
    sections = split_sections(BODY)

    assert [path for path, _ in sections] == ["", "Díjak", "Díjak > Kártyák", "Késedelem"]
    assert sections[0][1] == "Bevezető bekezdés a címsor előtt."
    assert sections[2][1].startswith("| Tétel | Díj |")
    assert "## ez nem címsor" in sections[3][1]  # inside a code block


def test_a_heading_without_text_of_its_own_stays_in_the_path_only() -> None:
    sections = split_sections("## Hitelek\n\n### Lakáshitel\n\nSzöveg.\n\n## Betétek\n\nMás.")

    assert sections == [("Hitelek > Lakáshitel", "Szöveg."), ("Betétek", "Más.")]


def test_short_sections_are_one_chunk_each() -> None:
    chunks = chunk_document(BODY)

    assert [c.section for c in chunks] == ["", "Díjak", "Díjak > Kártyák", "Késedelem"]
    assert [c.index for c in chunks] == [0, 1, 2, 3]
    assert all(c.token_count == estimate_tokens(c.content) for c in chunks)


def sentences(count: int, prefix: str = "Mondat") -> str:
    return " ".join(f"{prefix} {i}: a késedelmi kamat szabálya itt áll." for i in range(count))


def test_a_long_section_is_split_with_overlap_and_never_over_the_limit() -> None:
    body = "## Hosszú\n\n" + "\n\n".join(sentences(4, f"P{p}") for p in range(12))

    chunks = chunk_document(body, max_tokens=200, overlap_tokens=40)

    assert len(chunks) > 1
    assert {c.section for c in chunks} == {"Hosszú"}
    assert all(c.token_count <= 200 for c in chunks)
    for previous, chunk in pairwise(chunks):
        last_sentence = previous.content.rsplit(". ", 1)[-1]
        assert last_sentence in chunk.content  # the boundary sentence is in both


def test_a_long_table_keeps_its_header_in_every_part() -> None:
    rows = "\n".join(f"| Tétel {i} | {i * 100} Ft |" for i in range(80))
    body = f"## Díjak\n\n| Tétel | Díj |\n|---|---|\n{rows}"

    chunks = chunk_document(body, max_tokens=150)

    assert len(chunks) > 1
    assert all(c.content.startswith("| Tétel | Díj |\n|---|---|\n") for c in chunks)
    assert all(c.token_count <= 150 for c in chunks)
    body_rows = [line for c in chunks for line in c.content.split("\n")[2:]]
    assert body_rows == rows.split("\n")  # no row lost or repeated: no overlap from a table


@pytest.mark.parametrize(
    "text",
    [
        "Egyetlen nagyon hosszú mondat " + "szó " * 400,  # split at words
        "x" * 2000,  # no space at all: split at characters
    ],
)
def test_text_without_breaks_is_still_split(text: str) -> None:
    chunks = chunk_document(f"## Rész\n\n{text}", max_tokens=100, overlap_tokens=0)

    assert len(chunks) > 1
    assert all(c.token_count <= 100 for c in chunks)
    assert "".join(c.content.replace(" ", "") for c in chunks) == text.replace(" ", "")


def test_token_estimate() -> None:
    assert estimate_tokens("") == 0
    assert estimate_tokens("a" * CHARS_PER_TOKEN) == 1
    assert estimate_tokens("a" * (CHARS_PER_TOKEN + 1)) == 2


def test_every_repository_document_chunks_within_the_limit() -> None:
    for document in load_documents():
        chunks = chunk_document(document.body)
        assert chunks, document.source_path
        assert all(c.token_count <= 500 for c in chunks), document.source_path
        assert all(c.section for c in chunks[1:]), document.source_path  # only the intro has none

"""Heading-based chunking: every section is a chunk, and a section too long for one is split at
paragraph, line, sentence and, as a last resort, word boundaries, with a small overlap.

A chunk never crosses a heading: a citation names one section, and a chunk mixing two topics
matches both badly.
"""

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass

MAX_TOKENS = 500
OVERLAP_TOKENS = 60
# Hungarian text runs about three characters per token with the Claude and Voyage tokenizers.
# An estimate is enough: the limit only has to keep chunks focused and well under the
# embedding model's input limit.
CHARS_PER_TOKEN = 3
SECTION_SEPARATOR = " > "

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_PARAGRAPH_BREAK = re.compile(r"\n\s*\n")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True)
class Chunk:
    index: int  # position in the document
    section: str  # heading path, e.g. "Díjak > Kártyák"; empty before the first heading
    content: str
    token_count: int


def estimate_tokens(text: str) -> int:
    return math.ceil(len(text) / CHARS_PER_TOKEN)


def chunk_document(
    body: str, *, max_tokens: int = MAX_TOKENS, overlap_tokens: int = OVERLAP_TOKENS
) -> list[Chunk]:
    chunks: list[Chunk] = []
    for section, text in split_sections(body):
        for content in _pack(_pieces(text, max_tokens), max_tokens, overlap_tokens):
            chunks.append(Chunk(len(chunks), section, content, estimate_tokens(content)))
    return chunks


def split_sections(body: str) -> list[tuple[str, str]]:
    """(heading path, text) for every section that has text of its own. A heading directly
    followed by a subheading has none, but stays in its subsections' path."""
    sections: list[tuple[str, str]] = []
    headings: list[tuple[int, str]] = []  # (level, title) from the outermost
    lines: list[str] = []
    in_code = False

    def flush() -> None:
        text = "\n".join(lines).strip()
        if text:
            sections.append((SECTION_SEPARATOR.join(title for _, title in headings), text))
        lines.clear()

    for line in body.split("\n"):
        if line.lstrip().startswith("```"):
            in_code = not in_code
        match = None if in_code else _HEADING.match(line)
        if match is None:
            lines.append(line)
            continue
        flush()
        level = len(match[1])
        while headings and headings[-1][0] >= level:
            headings.pop()
        headings.append((level, match[2]))
    flush()
    return sections


def _pieces(text: str, max_tokens: int) -> list[str]:
    """Paragraphs (a table or a list is one), each split further if it is over the limit."""
    pieces: list[str] = []
    for block in _PARAGRAPH_BREAK.split(text):
        if block.strip():
            pieces.extend(_fit(block.strip(), max_tokens))
    return pieces


def _fit(block: str, max_tokens: int) -> list[str]:
    if estimate_tokens(block) <= max_tokens:
        return [block]
    lines = block.split("\n")
    if len(lines) > 1:
        # A table split in parts keeps its header in every part, or the numbers lose their
        # meaning.
        header = lines[:2] if _is_table(lines) else []
        return _group(lines[len(header) :], max_tokens, "\n", prefix="\n".join(header))
    sentences = _SENTENCE_END.split(block)
    if len(sentences) > 1:
        return _group(sentences, max_tokens, " ")
    words = block.split(" ")
    if len(words) > 1:
        return _group(words, max_tokens, " ")
    size = max_tokens * CHARS_PER_TOKEN
    return [block[i : i + size] for i in range(0, len(block), size)]


def _group(units: Sequence[str], max_tokens: int, joiner: str, *, prefix: str = "") -> list[str]:
    """Consecutive units joined into parts of at most max_tokens; a unit over the limit on its
    own is split further."""
    lead = prefix + joiner if prefix else ""
    budget = max_tokens - estimate_tokens(lead)
    parts: list[str] = []
    current: list[str] = []
    for unit in units:
        if estimate_tokens(unit) > budget:
            if current:
                parts.append(lead + joiner.join(current))
                current = []
            parts.extend(lead + part for part in _fit(unit, budget))
            continue
        if current and estimate_tokens(joiner.join([*current, unit])) > budget:
            parts.append(lead + joiner.join(current))
            current = []
        current.append(unit)
    if current:
        parts.append(lead + joiner.join(current))
    return parts


def _pack(pieces: Sequence[str], max_tokens: int, overlap_tokens: int) -> list[str]:
    """Pieces of one section joined into chunks. A new chunk starts with the last sentences of
    the previous one, so a statement cut at the boundary is still whole in one of them."""
    chunks: list[str] = []
    current: list[str] = []
    for piece in pieces:
        if current and estimate_tokens("\n\n".join([*current, piece])) > max_tokens:
            chunks.append("\n\n".join(current))
            tail = _tail(current[-1], overlap_tokens)
            fits = tail and estimate_tokens(f"{tail}\n\n{piece}") <= max_tokens
            current = [tail] if fits else []
        current.append(piece)
    if current:
        chunks.append("\n\n".join(current))
    return chunks


def _tail(text: str, overlap_tokens: int) -> str:
    """The last whole sentences of a paragraph within the overlap budget. None from a table: a
    row without its header means nothing."""
    if overlap_tokens <= 0 or _is_table(text.split("\n")):
        return ""
    tail: list[str] = []
    for sentence in reversed(_SENTENCE_END.split(text)):
        if estimate_tokens(" ".join([sentence, *tail])) > overlap_tokens:
            break
        tail.insert(0, sentence)
    return " ".join(tail)


def _is_table(lines: Sequence[str]) -> bool:
    return len(lines) >= 2 and lines[0].lstrip().startswith("|") and "---" in lines[1]

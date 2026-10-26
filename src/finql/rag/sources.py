"""The source documents: Markdown files with a YAML header (data/documents/README.md)."""

import hashlib
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from finql.rag.models import DocumentAccess

DOCUMENTS_DIR = Path("data/documents")
# Describes the directory, not a document.
IGNORED_FILES = frozenset({"README.md"})

type DocType = Literal[
    "fee_schedule", "rate_notice", "product_terms", "policy", "procedure", "glossary"
]


class DocumentError(ValueError):
    """A source file that cannot be loaded; the message names the file."""


class DocumentMeta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=3)
    doc_type: DocType
    access_level: DocumentAccess
    effective_from: date


@dataclass(frozen=True)
class SourceDocument:
    source_path: str  # the file name, relative to the documents directory
    meta: DocumentMeta
    body: str  # the Markdown after the header
    content_hash: str


def parse_document(source_path: str, text: str) -> SourceDocument:
    # A Windows checkout may have CRLF line endings; the hash must not depend on that.
    text = text.replace("\r\n", "\n")
    content_hash = hashlib.sha256(text.encode()).hexdigest()
    if not text.startswith("---\n"):
        raise DocumentError(f"{source_path}: nincs YAML-fejléc (---)")
    header, separator, body = text[4:].partition("\n---\n")
    if not separator:
        raise DocumentError(f"{source_path}: a YAML-fejléc nincs lezárva (---)")
    try:
        meta = DocumentMeta.model_validate(yaml.safe_load(header))
    except (yaml.YAMLError, ValidationError) as exc:
        raise DocumentError(f"{source_path}: hibás fejléc: {exc}") from exc
    if not body.strip():
        raise DocumentError(f"{source_path}: üres dokumentum")
    return SourceDocument(source_path, meta, body.strip(), content_hash)


def load_documents(directory: Path = DOCUMENTS_DIR) -> list[SourceDocument]:
    """Every *.md file of the directory (not recursive), sorted by name."""
    paths = sorted(p for p in directory.glob("*.md") if p.name not in IGNORED_FILES)
    return [parse_document(p.name, p.read_text(encoding="utf-8")) for p in paths]

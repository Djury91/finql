"""Versioned prompts. A changed prompt is a new file (`.v2`), so the query log and the eval runs
can tell which version produced an answer."""

from functools import lru_cache
from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parent


@lru_cache
def load_prompt(name: str) -> str:
    """`load_prompt("text_to_sql.v1")` → the text of text_to_sql.v1.md."""
    return (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")

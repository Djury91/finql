"""The document search mini-eval: does the expected document make the top k, and does an
internal document ever reach a branch manager?"""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from finql.auth.models import UserRole
from finql.rag.models import ROLE_ACCESS, DocumentAccess
from finql.rag.retriever import Retriever, SearchMode

RETRIEVAL_FILE = Path("eval/datasets/retrieval.yaml")
TOP_K = 5


class RetrievalQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9_]+$")
    question: str = Field(min_length=3)
    role: Literal["branch_manager", "analyst"] = "analyst"
    # Any of these in the top k is a hit. Empty: the question only checks for leaks.
    expected: list[str] = Field(default_factory=list)

    @property
    def access(self) -> DocumentAccess:
        return ROLE_ACCESS[UserRole(self.role)]


def load_retrieval(path: Path = RETRIEVAL_FILE) -> list[RetrievalQuestion]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    questions = [RetrievalQuestion.model_validate(item) for item in data["questions"]]
    ids = [q.id for q in questions]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate question ids in the retrieval set")
    return questions


@dataclass(frozen=True)
class RetrievalOutcome:
    question: RetrievalQuestion
    found: list[str]  # the documents of the top k chunks, in rank order, without repeats
    leaked: list[str]  # documents above the asker's reading level: must stay empty
    mode: SearchMode

    @property
    def rank(self) -> int | None:
        """1-based rank of the first expected document among the found ones."""
        for rank, path in enumerate(self.found, start=1):
            if path in self.question.expected:
                return rank
        return None


@dataclass(frozen=True)
class RetrievalMetrics:
    k: int
    measured: int  # questions with an expected document
    hits: int  # expected document in the top k
    mrr: float  # mean reciprocal rank (0 for a miss)
    leaks: int  # questions where an internal document reached a branch manager
    modes: list[SearchMode]

    @property
    def recall(self) -> float:
        return self.hits / self.measured if self.measured else 0.0


async def run_retrieval_eval(
    retriever: Retriever, questions: Sequence[RetrievalQuestion], *, top_k: int = TOP_K
) -> list[RetrievalOutcome]:
    outcomes = []
    for question in questions:
        result = await retriever.search(question.question, access=question.access, top_k=top_k)
        found = list(dict.fromkeys(hit.source_path for hit in result.hits))
        above = (h for h in result.hits if not question.access.covers(h.access_level))
        leaked = list(dict.fromkeys(hit.source_path for hit in above))
        outcomes.append(RetrievalOutcome(question, found, leaked, result.mode))
    return outcomes


def summarize_retrieval(outcomes: Sequence[RetrievalOutcome], *, k: int) -> RetrievalMetrics:
    measured = [o for o in outcomes if o.question.expected]
    ranks = [o.rank for o in measured]
    return RetrievalMetrics(
        k=k,
        measured=len(measured),
        hits=sum(1 for rank in ranks if rank is not None),
        mrr=sum(1 / rank for rank in ranks if rank is not None) / len(measured) if measured else 0,
        leaks=sum(1 for o in outcomes if o.leaked),
        modes=sorted({o.mode for o in outcomes}),
    )


def render_retrieval_report(
    outcomes: Sequence[RetrievalOutcome], metrics: RetrievalMetrics, *, embedding_model: str | None
) -> str:
    lines = [
        "# Dokumentumkeresés – eval",
        "",
        f"- Embedding: {embedding_model or 'nincs (csak teljes szöveges keresés)'}",
        f"- Keresési mód: {', '.join(metrics.modes)}",
        "",
        "| Mutató | Érték |",
        "|---|---|",
        f"| Recall@{metrics.k} | {metrics.hits}/{metrics.measured} ({_pct(metrics.recall)}) |",
        f"| MRR | {metrics.mrr:.3f}".replace(".", ",") + " |",
        f"| Szivárgás (belső dokumentum fiókvezetőnek) | {metrics.leaks} |",
        "",
        "| Kérdés | Szerepkör | Elvárt | Helyezés | Találatok |",
        "|---|---|---|---|---|",
    ]
    for o in outcomes:
        expected = ", ".join(o.question.expected) or "–"
        if o.leaked:
            rank = f"**szivárgás: {', '.join(o.leaked)}**"
        elif not o.question.expected:
            rank = "nincs szivárgás"
        else:
            rank = str(o.rank) if o.rank is not None else f"**nincs a top {metrics.k}-ben**"
        lines.append(
            f"| {o.question.id} | {o.question.role} | {expected} | {rank} | {', '.join(o.found)} |"
        )
    return "\n".join(lines) + "\n"


def _pct(value: float) -> str:
    return f"{100 * value:.1f}%".replace(".", ",")

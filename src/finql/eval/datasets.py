"""The question sets (eval/datasets/*.yaml): reviewed like code, versioned with the prompt."""

from pathlib import Path
from typing import Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

DATASETS_DIR = Path("eval/datasets")
GOLDEN_FILE = DATASETS_DIR / "golden.yaml"
ADVERSARIAL_FILE = DATASETS_DIR / "adversarial.yaml"

type Tag = Literal[
    "aggregation", "filter", "join", "time", "window", "ranking", "subquery", "branch"
]
type Difficulty = Literal["easy", "medium", "hard"]
type Role = Literal["analyst", "branch_manager"]


class _Question(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^[a-z0-9_]+$")
    question: str = Field(min_length=3)
    # Who asks: the data scope comes from the role, as in the API (text_to_sql.service).
    role: Role = "analyst"
    branch: str | None = Field(default=None, description="Fiókkód (pl. PEC01), fiókvezetőnél.")

    @model_validator(mode="after")
    def _branch_matches_role(self) -> Self:
        if (self.role == "branch_manager") != (self.branch is not None):
            raise ValueError(f"{self.id}: a branch csak és kizárólag fiókvezetőnél kötelező")
        return self


class GoldenQuestion(_Question):
    """A question with the SQL that answers it. The generated SQL is right when it returns the
    same result (eval.compare), whatever it looks like."""

    sql: str = Field(min_length=8)
    difficulty: Difficulty
    tags: list[Tag] = Field(min_length=1)
    # The order of the rows is part of the answer (a ranking). Otherwise any order is right, even
    # if the expected SQL has an ORDER BY: that is often only for readability.
    ordered: bool = False
    note: str | None = None


class AdversarialQuestion(_Question):
    """A question that must not return data: the model declines, the validator rejects it, or
    the database returns nothing."""

    category: Literal[
        "write", "pii", "prompt_injection", "cross_branch", "system", "admin", "unanswerable"
    ]


def _load[Q: _Question](path: Path, model: type[Q]) -> list[Q]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    questions = [model.model_validate(item) for item in data["questions"]]
    ids = [q.id for q in questions]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        raise ValueError(f"{path}: duplicate ids: {duplicates}")
    return questions


def load_golden(path: Path = GOLDEN_FILE) -> list[GoldenQuestion]:
    return _load(path, GoldenQuestion)


def load_adversarial(path: Path = ADVERSARIAL_FILE) -> list[AdversarialQuestion]:
    return _load(path, AdversarialQuestion)

"""Reject a query the planner expects to be expensive, before it runs (layer 3).

The statement timeout stops a slow query too, but only after it has held a connection and a CPU
core for seconds. The estimate costs a planning round (~1 ms) and turns away the obvious cases,
such as a cross join of two large views.
"""

import json
from dataclasses import dataclass
from typing import Any

from finql.core.errors import AppError


class QueryTooExpensiveError(AppError):
    status_code = 422
    code = "query_too_expensive"
    message = (
        "A lekérdezés túl nagy erőforrásigényű. Szűkítsd a kérdést (időszak, fiók, termék), "
        "vagy kérj összesített adatot."
    )

    def __init__(self, estimate: "PlanEstimate") -> None:
        super().__init__()
        self.estimate = estimate


@dataclass(frozen=True)
class PlanEstimate:
    total_cost: float  # the planner's cost units for the whole query
    max_rows: float  # the largest row estimate of any plan node (intermediate results too)


def parse_explain(raw: Any) -> PlanEstimate:
    """From `EXPLAIN (FORMAT JSON)` output: a JSON text (or already decoded list)."""
    document = json.loads(raw) if isinstance(raw, str) else raw
    plan = document[0]["Plan"]
    return PlanEstimate(total_cost=float(plan["Total Cost"]), max_rows=_max_rows(plan))


def _max_rows(node: dict[str, Any]) -> float:
    children = node.get("Plans", [])
    return max([float(node.get("Plan Rows", 0)), *(_max_rows(child) for child in children)])


def check_estimate(estimate: PlanEstimate, *, max_cost: float, max_plan_rows: float) -> None:
    if estimate.total_cost > max_cost or estimate.max_rows > max_plan_rows:
        raise QueryTooExpensiveError(estimate)

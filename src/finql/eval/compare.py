"""Execution accuracy: does the generated SQL return the expected result? How the SQL looks does
not matter, only what it returns.

The rules:
- The same number of rows.
- Every expected column is found among the generated ones by its values, not by its name (the
  model names columns freely). Extra generated columns are allowed, e.g. a branch name next to
  the expected branch code.
- Rows in order if the question asks for a ranking (`ordered`), otherwise as a multiset.
- Numbers are equal within ABS_TOLERANCE: a percentage rounded to one decimal (rule 9 of the
  prompt) still matches an unrounded one. A timestamp at midnight equals its date. Text is exact.
"""

import math
import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Any

ABS_TOLERANCE = 0.05
REL_TOLERANCE = 1e-9
# Stop trying column assignments after this many (wide results with many identical columns).
MAX_ASSIGNMENTS = 1000

_MIDNIGHT = re.compile(r"^(\d{4}-\d{2}-\d{2})T00:00:00(?:Z|[+-]\d{2}:\d{2})?$")

# A normalized value: a type rank (only equal ranks compare) and a comparable payload.
type Value = tuple[int, Any]


@dataclass(frozen=True)
class ResultSet:
    columns: list[str]
    rows: list[list[Any]]


@dataclass(frozen=True)
class Comparison:
    match: bool
    reason: str | None = None


def compare_results(expected: ResultSet, actual: ResultSet, *, ordered: bool) -> Comparison:
    if len(actual.rows) != len(expected.rows):
        return Comparison(False, f"{len(actual.rows)} sor, a várt {len(expected.rows)} helyett")
    if not expected.rows:
        return Comparison(True)
    if len(actual.columns) < len(expected.columns):
        return Comparison(
            False, f"{len(actual.columns)} oszlop, a várt {len(expected.columns)} helyett"
        )

    want = [[_normalize(row[j]) for row in expected.rows] for j in range(len(expected.columns))]
    got = [[_normalize(row[k]) for row in actual.rows] for k in range(len(actual.columns))]
    candidates = [
        [k for k, column in enumerate(got) if _columns_equal(wanted, column, ordered=ordered)]
        for wanted in want
    ]
    missing = [expected.columns[j] for j, found in enumerate(candidates) if not found]
    if missing:
        return Comparison(False, f"nincs egyező oszlop ehhez: {', '.join(missing)}")

    expected_rows = [list(row) for row in zip(*want, strict=True)]
    for mapping in _assignments(candidates):
        projected = [list(row) for row in zip(*(got[k] for k in mapping), strict=True)]
        if _rows_equal(expected_rows, projected, ordered=ordered):
            return Comparison(True)
    reason = "a sorrend eltér" if ordered else "az oszlopok egyeznek, de a sorok nem"
    return Comparison(False, reason)


def has_data(rows: Sequence[Sequence[Any]]) -> bool:
    """Anything beyond NULLs and zeros: a count of 0 for another branch reveals nothing."""
    return any(
        value is not None and not (_is_number(value) and value == 0)
        for row in rows
        for value in row
    )


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _normalize(value: Any) -> Value:
    if value is None:
        return (0, 0)
    if isinstance(value, bool):
        return (1, value)
    if _is_number(value):
        return (2, float(value))
    if isinstance(value, str):
        midnight = _MIDNIGHT.match(value)
        return (3, midnight.group(1) if midnight else value.strip())
    if isinstance(value, list | tuple):
        return (4, tuple(_normalize(item) for item in value))
    return (3, str(value))


def _equal(a: Value, b: Value) -> bool:
    if a[0] != b[0]:
        return False
    if a[0] == 2:
        return math.isclose(a[1], b[1], rel_tol=REL_TOLERANCE, abs_tol=ABS_TOLERANCE)
    return bool(a[1] == b[1])


def _columns_equal(a: list[Value], b: list[Value], *, ordered: bool) -> bool:
    # Sorted, numbers within the tolerance stay paired: in one dimension sorting gives the
    # closest pairing.
    if not ordered:
        a, b = sorted(a), sorted(b)
    return all(_equal(x, y) for x, y in zip(a, b, strict=True))


def _rows_equal(a: list[list[Value]], b: list[list[Value]], *, ordered: bool) -> bool:
    if not ordered:
        a, b = sorted(a), sorted(b)
    return all(
        all(_equal(x, y) for x, y in zip(row_a, row_b, strict=True))
        for row_a, row_b in zip(a, b, strict=True)
    )


def _assignments(candidates: list[list[int]]) -> Iterator[tuple[int, ...]]:
    """Injective choices: one generated column per expected column, each used at most once."""
    count = 0

    def extend(prefix: tuple[int, ...]) -> Iterator[tuple[int, ...]]:
        nonlocal count
        if len(prefix) == len(candidates):
            count += 1
            yield prefix
            return
        for k in candidates[len(prefix)]:
            if k not in prefix and count < MAX_ASSIGNMENTS:
                yield from extend((*prefix, k))

    yield from extend(())

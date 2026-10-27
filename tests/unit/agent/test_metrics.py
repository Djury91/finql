"""The metric catalog (data/metrics.yaml): it loads, and a name is found the way people ask."""

import pytest

from finql.agent.metrics import load_metrics, normalize

CATALOG = load_metrics()


def test_the_catalog_loads_and_names_are_unique() -> None:
    names = [normalize(n) for m in CATALOG.metrics for n in (m.name, *m.aliases)]
    assert len(CATALOG.metrics) >= 10
    assert len(names) == len(set(names))  # one name, one metric


@pytest.mark.parametrize(
    ("asked", "found"),
    [
        ("aktív ügyfél", "aktív ügyfél"),
        ("AKTIV UGYFEL", "aktív ügyfél"),  # case and accents do not matter
        ("NPL", "nem teljesítő hitel (NPL)"),
        ("npl-ráta", "NPL-ráta"),
        ("Mi számít aktív ügyfélnek?", "aktív ügyfél"),  # the name inside a question
        ("dpd", "késedelmi napok (DPD)"),
        ("kártyás forgalom", "kártyás költés"),
    ],
)
def test_find(asked: str, found: str) -> None:
    metric = CATALOG.find(asked)
    assert metric is not None and metric.name == found


@pytest.mark.parametrize("asked", ["kamatláb", "babaváró", "", "  "])
def test_unknown_names_are_not_matched_by_substrings(asked: str) -> None:
    # "ma" (today, an alias of the business day) is a substring of "kamatláb": no match.
    assert CATALOG.find(asked) is None

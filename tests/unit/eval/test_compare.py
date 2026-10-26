"""Execution accuracy: when two results count as the same answer."""

import pytest

from finql.eval.compare import ResultSet, compare_results, has_data

EXPECTED = ResultSet(["segment", "customers"], [["retail", 7659], ["premium", 1056], ["sme", 994]])


def test_any_row_order_and_any_column_names_match() -> None:
    actual = ResultSet(["szegmens", "db"], [["sme", 994], ["retail", 7659], ["premium", 1056]])

    assert compare_results(EXPECTED, actual, ordered=False).match


def test_columns_are_found_by_their_values_whatever_their_position() -> None:
    actual = ResultSet(["n", "segment"], [[7659, "retail"], [1056, "premium"], [994, "sme"]])

    assert compare_results(EXPECTED, actual, ordered=False).match


def test_extra_columns_are_allowed() -> None:
    actual = ResultSet(
        ["segment", "label", "customers"],
        [["retail", "Lakossági", 7659], ["premium", "Prémium", 1056], ["sme", "KKV", 994]],
    )

    assert compare_results(EXPECTED, actual, ordered=False).match


def test_a_wrong_value_fails() -> None:
    actual = ResultSet(
        ["segment", "customers"], [["retail", 7659], ["premium", 1057], ["sme", 994]]
    )

    result = compare_results(EXPECTED, actual, ordered=False)

    assert not result.match
    assert result.reason == "nincs egyező oszlop ehhez: customers"


def test_values_must_stay_together_in_their_rows() -> None:
    # Both columns hold the right values, but paired up wrongly.
    actual = ResultSet(
        ["segment", "customers"], [["retail", 1056], ["premium", 7659], ["sme", 994]]
    )

    result = compare_results(EXPECTED, actual, ordered=False)

    assert not result.match
    assert result.reason == "az oszlopok egyeznek, de a sorok nem"


@pytest.mark.parametrize(
    ("rows", "reason"),
    [
        ([["retail", 7659], ["premium", 1056]], "2 sor, a várt 3 helyett"),
        ([], "0 sor, a várt 3 helyett"),
    ],
)
def test_row_count_must_match(rows: list[list[object]], reason: str) -> None:
    result = compare_results(EXPECTED, ResultSet(["segment", "customers"], rows), ordered=False)

    assert (result.match, result.reason) == (False, reason)


def test_fewer_columns_fail() -> None:
    actual = ResultSet(["segment"], [["retail"], ["premium"], ["sme"]])

    assert compare_results(EXPECTED, actual, ordered=False).reason == "1 oszlop, a várt 2 helyett"


def test_order_matters_only_for_a_ranking() -> None:
    shuffled = ResultSet(
        ["segment", "customers"], [["sme", 994], ["retail", 7659], ["premium", 1056]]
    )

    assert compare_results(EXPECTED, shuffled, ordered=False).match
    result = compare_results(EXPECTED, shuffled, ordered=True)
    assert not result.match


@pytest.mark.parametrize(
    ("expected", "actual"),
    [
        (4.4, 4.37),  # a percentage rounded to one decimal (rule 9 of the prompt)
        (3.5, 3.5000001),
        (1056, 1056.0),  # integer vs float
        (12_345_678_901.25, 12_345_678_901.249),  # big sums: float rounding
    ],
)
def test_numbers_match_within_the_tolerance(expected: float, actual: float) -> None:
    assert compare_results(
        ResultSet(["x"], [[expected]]), ResultSet(["y"], [[actual]]), ordered=False
    ).match


@pytest.mark.parametrize(("expected", "actual"), [(4.4, 4.3), (100, 101), (0.044, 4.4)])
def test_numbers_outside_the_tolerance_differ(expected: float, actual: float) -> None:
    assert not compare_results(
        ResultSet(["x"], [[expected]]), ResultSet(["y"], [[actual]]), ordered=False
    ).match


@pytest.mark.parametrize(
    "actual",
    ["2025-09-01T00:00:00+02:00", "2025-09-01T00:00:00+00:00", "2025-09-01T00:00:00"],
)
def test_a_midnight_timestamp_equals_its_date(actual: str) -> None:
    assert compare_results(
        ResultSet(["month"], [["2025-09-01"]]), ResultSet(["m"], [[actual]]), ordered=False
    ).match


def test_a_timestamp_that_is_not_midnight_is_not_a_date() -> None:
    assert not compare_results(
        ResultSet(["month"], [["2025-09-01"]]),
        ResultSet(["m"], [["2025-08-31T22:00:00+00:00"]]),
        ordered=False,
    ).match


def test_types_do_not_mix() -> None:
    assert not compare_results(
        ResultSet(["x"], [["1"]]), ResultSet(["y"], [[1]]), ordered=False
    ).match
    assert not compare_results(
        ResultSet(["x"], [[True]]), ResultSet(["y"], [[1]]), ordered=False
    ).match


def test_nulls_compare_equal_and_sort_with_other_values() -> None:
    expected = ResultSet(["age_band", "n"], [["18-25", 1], [None, 5], ["66+", 3]])
    actual = ResultSet(["a", "b"], [[None, 5], ["66+", 3], ["18-25", 1]])

    assert compare_results(expected, actual, ordered=False).match


def test_identical_columns_are_assigned_one_to_one() -> None:
    # Two expected columns with the same values need two generated ones.
    expected = ResultSet(["a", "b"], [[1, 1], [2, 2]])

    assert compare_results(expected, ResultSet(["x", "y"], [[1, 1], [2, 2]]), ordered=False).match
    assert not compare_results(
        expected, ResultSet(["x", "label"], [[1, "p"], [2, "q"]]), ordered=False
    ).match


def test_empty_results_match() -> None:
    assert compare_results(ResultSet(["a"], []), ResultSet(["b", "c"], []), ordered=False).match


@pytest.mark.parametrize(
    ("rows", "expected"),
    [
        ([], False),
        ([[None]], False),
        ([[0]], False),
        ([[0, None, 0.0]], False),
        ([[1]], True),
        ([["Debreceni fiók"]], True),
        ([[False]], True),  # a boolean is information
    ],
)
def test_has_data(rows: list[list[object]], expected: bool) -> None:
    assert has_data(rows) is expected

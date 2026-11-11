import numpy as np
import pandas as pd
import pytest

from datasift import QueryError, filter_rows


@pytest.fixture
def df():
    return pd.DataFrame({
        "state": ["NC", "NC", "SC", "GA", "VA", "NC"],
        "county": ["Wake", "Durham", "Greenville", "Fulton", "Fairfax", "Hyde"],
        "pop": [1_100_000, 320_000, 520_000, 1_060_000, 1_150_000, 4_900],
        "change_pct": [22.6, 18.5, 15.0, 15.2, 6.0, -15.0],
        "Median Income": [80_000, 60_000, 55_000, 70_000, 125_000, np.nan],
        "metro": [True, True, True, True, True, False],
    })


def names(result):
    return list(result["county"])


@pytest.mark.parametrize("where, expected", [
    ("state = NC", ["Wake", "Durham", "Hyde"]),
    ("state == nc", ["Wake", "Durham", "Hyde"]),                  # case-insensitive
    ("state != NC", ["Greenville", "Fulton", "Fairfax"]),
    ("change_pct > 15", ["Wake", "Durham", "Fulton"]),
    ("change_pct >= 15", ["Wake", "Durham", "Greenville", "Fulton"]),
    ("change_pct < 0", ["Hyde"]),
    ("change_pct <= -15", ["Hyde"]),
    ("pop > 1000000", ["Wake", "Fulton", "Fairfax"]),
    ("change_pct between 10 and 20", ["Durham", "Greenville", "Fulton"]),
    ("state in (SC, GA)", ["Greenville", "Fulton"]),
    ("state in SC, GA", ["Greenville", "Fulton"]),                # no brackets
    ("state not in (NC, SC)", ["Fulton", "Fairfax"]),
    ("county contains AX", ["Fairfax"]),
    ("county startswith f", ["Fulton", "Fairfax"]),
    ("county endswith e", ["Wake", "Greenville", "Hyde"]),
    ("county not contains a", ["Greenville", "Fulton", "Hyde"]),
    ("`Median Income` is missing", ["Hyde"]),
    ("median_income is not missing and state = NC", ["Wake", "Durham"]),  # loose column match
    ("metro = false", ["Hyde"]),
    ('county = "Wake"', ["Wake"]),
])
def test_single_conditions(df, where, expected):
    assert names(filter_rows(df, where)) == expected


def test_and_binds_tighter_than_or(df):
    # Read as: (state = SC) or (state = NC and change_pct > 20)
    assert names(filter_rows(df, "state = SC or state = NC and change_pct > 20")) == ["Wake", "Greenville"]


def test_parentheses_override_precedence(df):
    assert names(filter_rows(df, "(state = SC or state = NC) and change_pct > 20")) == ["Wake"]


def test_not(df):
    assert names(filter_rows(df, "not (state = NC or change_pct < 10)")) == ["Greenville", "Fulton"]


def test_empty_filter_returns_everything(df):
    assert len(filter_rows(df, "")) == len(df)
    assert len(filter_rows(df, None)) == len(df)


def test_number_with_symbols(df):
    assert names(filter_rows(df, "`Median Income` >= $100000")) == ["Fairfax"]


@pytest.mark.parametrize("where, message", [
    ("stat = NC", "Did you mean: state"),
    ("county > Wake", "holds text"),
    ("pop > lots", "isn't a number"),
    ("(state = NC", "Missing a closing"),
    ("state = NC change_pct > 5", "forget 'and'"),
    ("state =", "ends too early"),
    ("county between 1 and 2", "needs numbers or dates"),
    ("   ", None),
])
def test_helpful_errors(df, where, message):
    if message is None:
        assert len(filter_rows(df, where)) == len(df)
        return
    with pytest.raises(QueryError, match=message):
        filter_rows(df, where)


def test_filters_cannot_run_code(df):
    with pytest.raises(QueryError):
        filter_rows(df, "__import__('os').system('echo hacked') = 1")

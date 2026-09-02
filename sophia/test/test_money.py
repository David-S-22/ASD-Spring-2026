"""Tests for sophia.backend.engine.money: cents-to-dollar formatting, and back."""
import pytest

from sophia.backend.engine.money import (
    format_actual,
    format_estimate,
    format_estimate_single,
    parse_dollars_to_cents,
)


def test_format_actual():
    assert format_actual(4200) == "$42.00"


def test_format_actual_thousands():
    assert format_actual(110000) == "$1,100.00"


def test_format_estimate_range():
    assert format_estimate(37900, 41500) == "$379–415"


def test_format_estimate_equal_bounds_collapses():
    assert format_estimate(37900, 37900) == "$379"


def test_format_estimate_single():
    assert format_estimate_single(43600) == "$436"


def test_format_estimate_single_rounds_half_up():
    assert format_estimate_single(4299) == "$43"


@pytest.mark.parametrize(
    "value,expected",
    [
        (15, 1500),
        (15.0, 1500),
        ("15", 1500),
        ("$15.00", 1500),
        ("1,100.00", 110000),
        (0.1, 10),
        (9.99, 999),
    ],
)
def test_parse_dollars_to_cents(value, expected):
    assert parse_dollars_to_cents(value) == expected


def test_parse_dollars_to_cents_is_exact_where_float_is_not():
    """16.45 * 100 is 1644.9999999999998 as a float; a cent must not go missing."""
    assert parse_dollars_to_cents(16.45) == 1645
    assert parse_dollars_to_cents("16.45") == 1645


def test_parse_dollars_to_cents_rounds_half_up():
    assert parse_dollars_to_cents("0.005") == 1


@pytest.mark.parametrize("value", ["", "   ", "abc", True, None])
def test_parse_dollars_to_cents_rejects_non_amounts(value):
    with pytest.raises(ValueError):
        parse_dollars_to_cents(value)

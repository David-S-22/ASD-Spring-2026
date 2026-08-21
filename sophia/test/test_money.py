"""Tests for sophia.backend.engine.money: cents-to-dollar formatting."""
from sophia.backend.engine.money import format_actual, format_estimate, format_estimate_single


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

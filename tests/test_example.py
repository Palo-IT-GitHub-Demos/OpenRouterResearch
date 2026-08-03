"""Example test module — replace with your own business logic tests.

Run with: pytest  (or: make test)
"""
from __future__ import annotations


# ── Example function to test ───────────────────────────────────────────────────

def add(a: int, b: int) -> int:
    """Return the sum of two integers."""
    return a + b


def divide(a: float, b: float) -> float:
    """Return a divided by b. Raises ValueError on division by zero."""
    if b == 0:
        raise ValueError("Division by zero is not allowed.")
    return a / b


# ── Test cases ─────────────────────────────────────────────────────────────────

class TestAdd:
    def test_positive_numbers(self) -> None:
        assert add(1, 2) == 3

    def test_negative_numbers(self) -> None:
        assert add(-1, -1) == -2

    def test_zero(self) -> None:
        assert add(0, 0) == 0


class TestDivide:
    def test_basic_division(self) -> None:
        assert divide(10.0, 2.0) == 5.0

    def test_division_by_zero_raises(self) -> None:
        import pytest
        with pytest.raises(ValueError, match="Division by zero"):
            divide(1.0, 0.0)

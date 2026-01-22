"""Tests for return calculations."""

import pytest
from dm.returns import calculate_simple_return, convert_treasury_rate, calculate_weighted_return


class TestSimpleReturn:
    """Tests for simple return calculation."""

    def test_positive_return(self):
        """Test calculating a positive return."""
        result = calculate_simple_return(start_price=100.0, end_price=110.0)
        assert result == pytest.approx(0.10)

    def test_negative_return(self):
        """Test calculating a negative return."""
        result = calculate_simple_return(start_price=100.0, end_price=90.0)
        assert result == pytest.approx(-0.10)

    def test_zero_return(self):
        """Test calculating zero return."""
        result = calculate_simple_return(start_price=100.0, end_price=100.0)
        assert result == pytest.approx(0.0)

    def test_fractional_prices(self):
        """Test with fractional prices."""
        result = calculate_simple_return(start_price=150.25, end_price=165.275)
        assert result == pytest.approx(0.10)


class TestTreasuryRateConversion:
    """Tests for converting annualized treasury rate to period returns."""

    def test_one_month_conversion(self):
        """Test converting annual rate to 1-month return."""
        result = convert_treasury_rate(annual_rate=0.05, months=1)
        assert result == pytest.approx(0.05 / 12)

    def test_three_month_conversion(self):
        """Test converting annual rate to 3-month return."""
        result = convert_treasury_rate(annual_rate=0.05, months=3)
        assert result == pytest.approx(0.05 / 4)

    def test_six_month_conversion(self):
        """Test converting annual rate to 6-month return."""
        result = convert_treasury_rate(annual_rate=0.05, months=6)
        assert result == pytest.approx(0.05 / 2)

    def test_zero_rate(self):
        """Test with zero rate."""
        result = convert_treasury_rate(annual_rate=0.0, months=1)
        assert result == pytest.approx(0.0)


class TestWeightedReturn:
    """Tests for weighted return calculation."""

    def test_equal_returns(self):
        """Test weighted average with equal returns."""
        returns = [0.05, 0.05, 0.05]
        result = calculate_weighted_return(returns)
        assert result == pytest.approx(0.05)

    def test_different_returns(self):
        """Test weighted average with different returns."""
        returns = [0.03, 0.06, 0.09]
        result = calculate_weighted_return(returns)
        assert result == pytest.approx(0.06)  # (0.03 + 0.06 + 0.09) / 3

    def test_mixed_positive_negative(self):
        """Test weighted average with mixed returns."""
        returns = [0.10, -0.05, 0.01]
        result = calculate_weighted_return(returns)
        assert result == pytest.approx(0.02)  # (0.10 - 0.05 + 0.01) / 3

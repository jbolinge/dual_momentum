"""Integration tests that call real external APIs.

Run with: uv run pytest -m integration
Skip with: uv run pytest -m "not integration"
"""

import subprocess
from datetime import date

import pytest

from dm.data import get_price, get_treasury_rate
from dm.cli import get_returns_for_symbol, get_treasury_returns


pytestmark = pytest.mark.integration


class TestYFinanceIntegration:
    """Integration tests for yfinance data fetching."""

    def test_get_voo_price(self):
        """Test fetching real VOO price."""
        today = date.today()
        price = get_price("VOO", today)

        assert isinstance(price, float)
        assert price > 0
        # VOO should be roughly in the $400-600 range (as of 2024-2025)
        assert 100 < price < 1000

    def test_get_vxus_price(self):
        """Test fetching real VXUS price."""
        today = date.today()
        price = get_price("VXUS", today)

        assert isinstance(price, float)
        assert price > 0
        # VXUS should be roughly in the $50-80 range
        assert 20 < price < 200

    def test_get_returns_for_voo(self):
        """Test calculating real returns for VOO."""
        today = date.today()
        returns_1m, returns_3m, returns_6m = get_returns_for_symbol("VOO", today)

        # Returns should be reasonable percentages (not extreme)
        for ret in [returns_1m, returns_3m, returns_6m]:
            assert isinstance(ret, float)
            assert -0.5 < ret < 0.5  # Between -50% and +50%


class TestFREDIntegration:
    """Integration tests for FRED API data fetching."""

    def test_get_treasury_rate(self):
        """Test fetching real treasury rate from FRED."""
        today = date.today()
        rate = get_treasury_rate(today)

        assert isinstance(rate, float)
        # Treasury rate should be between 0% and 10%
        assert 0 <= rate <= 0.10

    def test_get_treasury_returns(self):
        """Test calculating treasury returns for all periods."""
        today = date.today()
        returns_1m, returns_3m, returns_6m = get_treasury_returns(today)

        # All should be positive (assuming positive rates)
        for ret in [returns_1m, returns_3m, returns_6m]:
            assert isinstance(ret, float)
            assert ret >= 0

        # Returns should scale: 6m > 3m > 1m
        assert returns_6m > returns_3m > returns_1m


class TestCLIIntegration:
    """Integration tests for the full CLI."""

    def test_cli_runs_successfully(self):
        """Test that the CLI runs and produces expected output."""
        result = subprocess.run(
            ["uv", "run", "dm"],
            capture_output=True,
            text=True,
            timeout=60,
        )

        assert result.returncode == 0
        assert "Dual Momentum Analysis" in result.stdout
        assert "VOO:" in result.stdout
        assert "VXUS:" in result.stdout
        assert "Treasury:" in result.stdout
        assert "Winner" in result.stdout

    def test_cli_output_structure(self):
        """Test that CLI output has correct structure."""
        result = subprocess.run(
            ["uv", "run", "dm"],
            capture_output=True,
            text=True,
            timeout=60,
        )

        lines = result.stdout.strip().split("\n")

        # Check header
        assert "Dual Momentum Analysis" in lines[0]

        # Check that percentages are present
        assert any("%" in line for line in lines)

        # Check for period labels
        output = result.stdout
        assert "1-Month:" in output
        assert "3-Month:" in output
        assert "6-Month:" in output
        assert "Weighted:" in output

"""Tests for CLI output."""

from unittest.mock import patch


from dm.cli import main, format_output
from dm.compare import InstrumentReturns


class TestFormatOutput:
    """Tests for output formatting."""

    def test_format_output_single_winner(self):
        """Test output format with single winner."""
        voo = InstrumentReturns(
            name="VOO",
            returns_1m=0.05,
            returns_3m=0.08,
            returns_6m=0.12,
            weighted_return=0.0833,
        )
        vxus = InstrumentReturns(
            name="VXUS",
            returns_1m=0.03,
            returns_3m=0.05,
            returns_6m=0.07,
            weighted_return=0.05,
        )
        treasury = InstrumentReturns(
            name="Treasury",
            returns_1m=0.004,
            returns_3m=0.012,
            returns_6m=0.024,
            weighted_return=0.0133,
        )
        winners = [voo]

        output = format_output(voo, vxus, treasury, winners)

        assert "VOO" in output
        assert "VXUS" in output
        assert "Treasury" in output
        assert "5.00%" in output  # VOO 1m
        assert "8.00%" in output  # VOO 3m
        assert "12.00%" in output  # VOO 6m
        assert "8.33%" in output  # VOO weighted
        assert "Signal: VOO" in output

    def test_format_output_multiple_winners(self):
        """Test output format with multiple winners (tie)."""
        voo = InstrumentReturns(
            name="VOO",
            returns_1m=0.05,
            returns_3m=0.05,
            returns_6m=0.05,
            weighted_return=0.05,
        )
        vxus = InstrumentReturns(
            name="VXUS",
            returns_1m=0.05,
            returns_3m=0.05,
            returns_6m=0.05,
            weighted_return=0.05,
        )
        treasury = InstrumentReturns(
            name="Treasury",
            returns_1m=0.01,
            returns_3m=0.01,
            returns_6m=0.01,
            weighted_return=0.01,
        )
        winners = [voo, vxus]

        output = format_output(voo, vxus, treasury, winners)

        assert "Signal: VOO, VXUS" in output


class TestMain:
    """Tests for main CLI function."""

    @patch("dm.cli.get_price")
    @patch("dm.cli.get_treasury_rate")
    def test_main_produces_output(self, mock_treasury, mock_price, capsys):
        """Test that main produces expected output structure."""

        # Mock price data: start and end prices for 1, 3, 6 months
        # VOO: starts at 100, ends at 105 (5% return for simplicity)
        # VXUS: starts at 50, ends at 51.5 (3% return)
        def price_side_effect(symbol, date):
            if symbol == "VOO":
                return 105.0  # Current price
            else:
                return 51.5  # Current VXUS price

        mock_price.side_effect = price_side_effect

        # Treasury rate 5% annual
        mock_treasury.return_value = 0.05

        # Override to return consistent mock data
        with patch("dm.cli.get_price") as mock_p:
            # Return different prices based on how far back we go
            call_count = {"VOO": 0, "VXUS": 0}

            def dynamic_price(symbol, date):
                call_count[symbol] += 1
                if symbol == "VOO":
                    # Current=105, 1m ago=100, 3m ago=97, 6m ago=94
                    prices = [105.0, 100.0, 97.0, 94.0]
                    return prices[min(call_count[symbol] - 1, 3)]
                else:  # VXUS
                    # Current=51.5, 1m ago=50, 3m ago=49, 6m ago=48
                    prices = [51.5, 50.0, 49.0, 48.0]
                    return prices[min(call_count[symbol] - 1, 3)]

            mock_p.side_effect = dynamic_price

            with patch("dm.cli.get_treasury_rate", return_value=0.05):
                main()

        captured = capsys.readouterr()
        output = captured.out

        # Verify output contains expected sections
        assert "VOO" in output
        assert "VXUS" in output
        assert "Treasury" in output
        assert "1-Month" in output or "1m" in output.lower()
        assert "Signal" in output

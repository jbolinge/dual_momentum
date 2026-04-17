"""Tests for CLI output."""

from datetime import date
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

    @patch("dm.cli.get_treasury_rate")
    @patch("dm.cli.select_price_on_or_before")
    @patch("dm.cli.get_price_history")
    def test_main_produces_output(
        self, mock_history, mock_select, mock_treasury, capsys
    ):
        """Main composes the history fetch + per-date lookups + treasury call."""
        mock_history.return_value = [(date(2024, 1, 1), 100.0)]

        # Return a sequence of prices so 1m/3m/6m returns are non-zero and
        # differ between VOO and VXUS. 8 selects total (4 per symbol).
        voo_prices = [105.0, 100.0, 97.0, 94.0]
        vxus_prices = [51.5, 50.0, 49.0, 48.0]

        call_count = {"VOO": 0, "VXUS": 0}

        def select_side_effect(bars, target_date, symbol):
            prices = voo_prices if symbol == "VOO" else vxus_prices
            value = prices[call_count[symbol]]
            call_count[symbol] += 1
            return value

        mock_select.side_effect = select_side_effect
        mock_treasury.return_value = 0.05

        main()

        captured = capsys.readouterr()
        output = captured.out
        assert "VOO" in output
        assert "VXUS" in output
        assert "Treasury" in output
        assert "1-Month" in output
        assert "Signal" in output

    @patch("dm.cli.get_treasury_rate", return_value=0.05)
    @patch("dm.cli.select_price_on_or_before", return_value=100.0)
    @patch("dm.cli.get_price_history")
    def test_one_history_fetch_per_symbol(
        self, mock_history, _mock_select, _mock_treasury, capsys
    ):
        """Regression: credits budget. Exactly one get_price_history call per symbol."""
        mock_history.return_value = [(date(2024, 1, 1), 100.0)]

        main()

        assert mock_history.call_count == 2
        called_symbols = sorted(call.args[0] for call in mock_history.call_args_list)
        assert called_symbols == ["VOO", "VXUS"]

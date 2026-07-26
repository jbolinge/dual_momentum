"""Tests for CLI orchestration and output."""

import re
from datetime import date
from unittest.mock import patch

import pytest

from dm.cli import (
    BOND_TICKER,
    INTL_TICKER,
    US_TICKER,
    build_signal,
    format_output,
    main,
)
from dm.signals import SignalResult

_MONTH_ENDS = [
    date(2025, 12, 31),
    date(2026, 1, 30),
    date(2026, 2, 27),
    date(2026, 3, 31),
    date(2026, 4, 30),
    date(2026, 5, 29),
    date(2026, 6, 30),
]

TODAY = date(2026, 7, 15)


def _bars(closes: list[float]) -> list[tuple[date, float]]:
    """Month-end bars (Dec 2025 .. Jun 2026) plus one mid-July bar."""
    return list(zip(_MONTH_ENDS, closes)) + [(date(2026, 7, 10), closes[-1])]


def _rates(annual: float = 0.048) -> list[tuple[date, float]]:
    return [(d, annual) for d in [date(2025, 11, 28)] + _MONTH_ENDS]


def _result(
    signal: str = "VXUS",
    relative_winner: str = "VXUS",
    us_score: float = 0.0495,
    intl_score: float = 0.0984,
    rf_score: float = 0.0104,
) -> SignalResult:
    return SignalResult(
        as_of=date(2026, 6, 30),
        us_returns={1: 0.0078, 3: 0.0366, 6: 0.1043},
        intl_returns={1: 0.0527, 3: 0.0838, 6: 0.1587},
        rf_returns={1: 0.0031, 3: 0.0094, 6: 0.0188},
        us_score=us_score,
        intl_score=intl_score,
        rf_score=rf_score,
        relative_winner=relative_winner,
        signal=signal,
    )


class TestTickers:
    """The CLI trades the user's live tickers."""

    def test_pv_ticker_mapping(self):
        assert (US_TICKER, INTL_TICKER, BOND_TICKER) == ("VOO", "VXUS", "VGIT")


class TestFormatOutput:
    """Tests for output formatting."""

    def test_reports_each_instrument(self):
        output = format_output(_result())

        assert "VOO:" in output
        assert "VXUS:" in output
        assert "T-bill" in output

    def test_reports_lookback_returns_and_scores(self):
        output = format_output(_result())

        assert "0.78%" in output  # VOO 1m
        assert "3.66%" in output  # VOO 3m
        assert "10.43%" in output  # VOO 6m
        assert "4.95%" in output  # VOO score
        assert "5.27%" in output  # VXUS 1m
        assert "9.84%" in output  # VXUS score
        assert "1.04%" in output  # risk-free score

    def test_reports_as_of_month_end(self):
        output = format_output(_result())

        assert "2026-06-30" in output

    def test_signal_line_is_greppable(self):
        output = format_output(_result())

        assert re.search(r"^Signal: VXUS\b", output, re.MULTILINE)

    def test_reports_relative_momentum_winner(self):
        output = format_output(_result())

        assert re.search(r"^Relative momentum: VXUS\b", output, re.MULTILINE)

    def test_reports_absolute_momentum_pass(self):
        output = format_output(_result())

        assert re.search(r"^Absolute momentum:", output, re.MULTILINE)
        assert "VGIT" not in output

    def test_now_mode_labels_the_latest_close(self):
        output = format_output(_result(), now=True)

        assert "(latest close)" in output
        assert "(month-end close)" not in output
        assert re.search(r"^Signal: VXUS \(as of 2026-06-30\)", output, re.MULTILINE)

    def test_month_end_mode_labels_the_month_end_close(self):
        output = format_output(_result())

        assert "(month-end close)" in output
        assert re.search(
            r"^Signal: VXUS \(hold from 2026-06-30\)", output, re.MULTILINE
        )

    def test_reports_absolute_momentum_failure(self):
        output = format_output(
            _result(
                signal="VGIT",
                relative_winner="VOO",
                us_score=-0.0752,
                intl_score=-0.1530,
                rf_score=0.0104,
            )
        )

        assert re.search(r"^Relative momentum: VOO\b", output, re.MULTILINE)
        assert "VGIT" in output
        assert re.search(r"^Signal: VGIT\b", output, re.MULTILINE)


class TestBuildSignal:
    """Tests for the fetch-and-compute orchestration."""

    def _patched(self, us_closes, intl_closes, rates=None):
        histories = {
            US_TICKER: _bars(us_closes),
            INTL_TICKER: _bars(intl_closes),
        }
        history_patch = patch(
            "dm.cli.get_price_history",
            side_effect=lambda symbol, start, end: histories[symbol],
        )
        rates_patch = patch(
            "dm.cli.get_tbill_rates", return_value=rates if rates else _rates()
        )
        return history_patch, rates_patch

    def test_anchors_on_latest_completed_month_end(self):
        history_patch, rates_patch = self._patched(
            [100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 110.0], [50.0] * 7
        )
        with history_patch, rates_patch:
            result = build_signal(TODAY)

        assert result.as_of == date(2026, 6, 30)
        assert result.us_returns[1] == pytest.approx(110.0 / 105.0 - 1)
        assert result.signal == "VOO"

    def test_uses_pv_tickers(self):
        history_patch, rates_patch = self._patched(
            [100.0] * 7, [50.0, 51.0, 52.0, 53.0, 54.0, 55.0, 60.0]
        )
        with history_patch as mock_history, rates_patch:
            result = build_signal(TODAY)

        assert sorted(call.args[0] for call in mock_history.call_args_list) == [
            "VOO",
            "VXUS",
        ]
        assert result.signal == "VXUS"

    def test_one_history_fetch_per_symbol(self):
        """Regression: credits budget. Exactly one price fetch per symbol."""
        history_patch, rates_patch = self._patched([100.0] * 7, [50.0] * 7)
        with history_patch as mock_history, rates_patch:
            build_signal(TODAY)

        assert mock_history.call_count == 2

    def test_fetches_enough_history_for_the_six_month_lookback(self):
        history_patch, rates_patch = self._patched([100.0] * 7, [50.0] * 7)
        with history_patch as mock_history, rates_patch:
            build_signal(TODAY)

        for call in mock_history.call_args_list:
            _symbol, start, end = call.args
            assert start <= date(2025, 12, 1)  # covers the Dec 2025 month end
            assert end == TODAY

    def test_fetches_rates_covering_the_risk_free_windows(self):
        history_patch, rates_patch = self._patched([100.0] * 7, [50.0] * 7)
        with history_patch, rates_patch as mock_rates:
            build_signal(TODAY)

        start, end = mock_rates.call_args.args
        # The 6-month window's first month is Jan 2026, whose rate is set at
        # the end of Dec 2025.
        assert start <= date(2025, 12, 1)
        assert end == TODAY

    def test_risk_free_returns_come_from_the_tbill_series(self):
        history_patch, rates_patch = self._patched(
            [100.0] * 7, [50.0] * 7, rates=_rates(0.12)
        )
        with history_patch, rates_patch:
            result = build_signal(TODAY)

        assert result.rf_returns[1] == pytest.approx(0.01)
        assert result.rf_returns[6] == pytest.approx(1.01**6 - 1)
        # Flat equities lose to a positive risk-free rate.
        assert result.signal == "VGIT"

    def test_now_mode_anchors_on_the_latest_bar(self):
        """--now prices the signal at the July 10 bar, not the June 30 close."""
        history_patch, rates_patch = self._patched(
            [100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 110.0], [50.0] * 7
        )
        with history_patch, rates_patch:
            result = build_signal(TODAY, now=True)

        assert result.as_of == date(2026, 7, 10)
        # No bar on June 10, so the 1-month leg falls back to the May 29 close.
        assert result.us_returns[1] == pytest.approx(110.0 / 105.0 - 1)

    def test_now_mode_risk_free_windows_follow_the_now_anchor(self):
        """The rf windows are shifted from July 10, not from a month end."""
        # Only the June 10 observation may feed the 1-month window.
        rates = [(d, 0.0) for d in [date(2025, 11, 28)] + _MONTH_ENDS[:-1]]
        rates += [(date(2026, 6, 10), 0.12), (date(2026, 6, 30), 0.0)]
        history_patch, rates_patch = self._patched(
            [100.0] * 7, [50.0] * 7, rates=sorted(rates)
        )
        with history_patch, rates_patch:
            result = build_signal(TODAY, now=True)

        assert result.rf_returns[1] == pytest.approx(0.01)

    def test_now_mode_still_fetches_once_per_symbol(self):
        history_patch, rates_patch = self._patched([100.0] * 7, [50.0] * 7)
        with history_patch as mock_history, rates_patch:
            build_signal(TODAY, now=True)

        assert mock_history.call_count == 2

    def test_risk_free_windows_use_the_shared_anchor_month(self):
        """If one equity series lags, the rf windows must follow the SHARED anchor.

        `compute_signal` anchors both funds on the latest month present in both,
        so anchoring the risk-free accumulation on the leading series alone would
        shift every rf window a month forward against the equity returns.
        """
        histories = {
            US_TICKER: list(zip(_MONTH_ENDS, [100.0] * 7))
            + [(date(2026, 7, 31), 100.0)],
            INTL_TICKER: list(zip(_MONTH_ENDS, [50.0] * 7)),  # no July bar
        }
        # Only the June month-end rate is non-zero. A June anchor earns month m
        # the rate set at the end of month m-1, so June's rate can never appear
        # in any window; a (wrong) July anchor puts it in all three.
        rates = [(d, 0.0) for d in [date(2025, 11, 28)] + _MONTH_ENDS[:-1]]
        rates.append((date(2026, 6, 30), 0.12))

        history_patch = patch(
            "dm.cli.get_price_history",
            side_effect=lambda symbol, start, end: histories[symbol],
        )
        rates_patch = patch("dm.cli.get_tbill_rates", return_value=rates)
        with history_patch, rates_patch:
            result = build_signal(date(2026, 7, 31))

        assert result.as_of == date(2026, 6, 30)
        assert result.rf_returns == {
            1: pytest.approx(0.0),
            3: pytest.approx(0.0),
            6: pytest.approx(0.0),
        }


class TestMain:
    """Tests for the main entry point."""

    @patch("dm.cli.get_tbill_rates", return_value=_rates())
    @patch("dm.cli.get_price_history")
    def test_prints_report(self, mock_history, _mock_rates, capsys):
        mock_history.side_effect = lambda symbol, start, end: _bars(
            [100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 110.0]
            if symbol == US_TICKER
            else [50.0] * 7
        )

        main(today=TODAY, argv=[])

        output = capsys.readouterr().out
        assert "VOO:" in output
        assert "VXUS:" in output
        assert "1-Month" in output
        assert "2026-06-30" in output
        assert re.search(r"^Signal: VOO\b", output, re.MULTILINE)

    @patch("dm.cli.get_tbill_rates", return_value=_rates())
    @patch("dm.cli.get_price_history")
    def test_defaults_to_today(self, mock_history, _mock_rates, capsys):
        mock_history.side_effect = lambda symbol, start, end: _bars([100.0] * 7)

        main(argv=[])

        _symbol, _start, end = mock_history.call_args.args
        assert end == date.today()
        assert "Signal:" in capsys.readouterr().out

    @patch("dm.cli.get_tbill_rates", return_value=_rates())
    @patch("dm.cli.get_price_history")
    def test_now_flag_reports_the_latest_close(self, mock_history, _mock_rates, capsys):
        mock_history.side_effect = lambda symbol, start, end: _bars(
            [100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 110.0]
            if symbol == US_TICKER
            else [50.0] * 7
        )

        main(today=TODAY, argv=["--now"])

        output = capsys.readouterr().out
        assert "As of: 2026-07-10 (latest close)" in output
        assert re.search(r"^Signal: VOO\b", output, re.MULTILINE)

    @patch("dm.cli.get_tbill_rates", return_value=_rates())
    @patch("dm.cli.get_price_history")
    def test_without_flag_keeps_month_end_anchor(
        self, mock_history, _mock_rates, capsys
    ):
        mock_history.side_effect = lambda symbol, start, end: _bars(
            [100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 110.0]
            if symbol == US_TICKER
            else [50.0] * 7
        )

        main(today=TODAY, argv=[])

        assert "As of: 2026-06-30 (month-end close)" in capsys.readouterr().out

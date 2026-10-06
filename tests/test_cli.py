"""Tests for CLI orchestration and output."""

import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from unittest.mock import patch

import pytest

from dm.cli import (
    BOND_TICKER,
    INTL_TICKER,
    US_TICKER,
    build_signal,
    format_output,
    main,
    session_date,
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


def _daily_bars(
    start: date, end: date, price=lambda day: 100.0
) -> list[tuple[date, float]]:
    """One bar per weekday from `start` to `end` inclusive."""
    bars = []
    day = start
    while day <= end:
        if day.weekday() < 5:
            bars.append((day, price(day)))
        day += timedelta(days=1)
    return bars


def _daily_rates(annual: float = 0.048) -> list[tuple[date, float]]:
    return [(d, annual) for d, _ in _daily_bars(date(2025, 11, 1), date(2026, 12, 31))]


# Trailing-mode fixtures: weekday closes through Mon Oct 5 2026, run Oct 6.
RUN_DAY = date(2026, 10, 6)


def _rising(day: date) -> float:
    return 100.0 + (day - date(2025, 11, 1)).days * 0.1


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
        window_starts={
            1: date(2026, 5, 31),
            3: date(2026, 3, 31),
            6: date(2025, 12, 31),
        },
    )


_ET = ZoneInfo("America/New_York")


class TestSessionDate:
    """The default run date is the latest session whose close has posted."""

    def test_after_the_close_uses_today(self):
        assert session_date(datetime(2026, 10, 6, 17, 0, tzinfo=_ET)) == date(
            2026, 10, 6
        )

    def test_during_the_session_uses_yesterday(self):
        """A mid-session bar is a live quote, not a close."""
        assert session_date(datetime(2026, 10, 6, 11, 0, tzinfo=_ET)) == date(
            2026, 10, 5
        )

    def test_before_the_close_is_posted_uses_yesterday(self):
        assert session_date(datetime(2026, 10, 6, 16, 5, tzinfo=_ET)) == date(
            2026, 10, 5
        )

    def test_converts_other_timezones_to_new_york(self):
        """3:30pm Central is 4:30pm Eastern: the close has posted."""
        central = ZoneInfo("America/Chicago")
        assert session_date(datetime(2026, 10, 6, 15, 30, tzinfo=central)) == date(
            2026, 10, 6
        )

    def test_month_end_mid_session_is_not_a_month_end_close(self):
        """Sep 30 at 11am ET: September's final close does not exist yet."""
        assert session_date(datetime(2026, 9, 30, 11, 0, tzinfo=_ET)) == date(
            2026, 9, 29
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

    def test_trailing_mode_labels_the_latest_close(self):
        output = format_output(_result())

        assert "(latest close, trailing windows)" in output
        assert "(month-end close)" not in output
        assert re.search(r"^Signal: VXUS \(as of 2026-06-30\)", output, re.MULTILINE)

    def test_reports_window_start_dates(self):
        output = format_output(_result())

        assert "Windows from: 1M 2026-05-31, 3M 2026-03-31, 6M 2025-12-31" in output

    def test_month_end_mode_labels_the_month_end_close(self):
        output = format_output(_result(), month_end=True)

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


class TestBuildSignalTrailing:
    """Default orchestration: trailing windows ending at the latest close."""

    def _patched(self, us_bars, intl_bars, rates=None):
        histories = {US_TICKER: us_bars, INTL_TICKER: intl_bars}
        history_patch = patch(
            "dm.cli.get_price_history",
            side_effect=lambda symbol, start, end: [
                bar for bar in histories[symbol] if start <= bar[0] <= end
            ],
        )
        rates_patch = patch(
            "dm.cli.get_tbill_rates",
            side_effect=lambda start, end: [
                obs
                for obs in (rates if rates is not None else _daily_rates())
                if start <= obs[0] <= end
            ],
        )
        return history_patch, rates_patch

    def test_default_anchors_on_the_latest_close(self):
        bars = _daily_bars(date(2025, 11, 1), date(2026, 10, 5), _rising)
        history_patch, rates_patch = self._patched(
            bars, _daily_bars(date(2025, 11, 1), date(2026, 10, 5))
        )
        with history_patch, rates_patch:
            result = build_signal(RUN_DAY)

        assert result.as_of == date(2026, 10, 5)

    def test_default_returns_are_trailing_from_the_run_date(self):
        """Run Oct 6: the 1-month leg runs from the Sep 4 close (Sep 5 is a
        Saturday) to Oct 5 — not from the Sep 30 month end."""
        bars = _daily_bars(date(2025, 11, 1), date(2026, 10, 5), _rising)
        history_patch, rates_patch = self._patched(bars, bars)
        with history_patch, rates_patch:
            result = build_signal(RUN_DAY)

        assert result.us_returns[1] == pytest.approx(
            _rising(date(2026, 10, 5)) / _rising(date(2026, 9, 4)) - 1
        )
        assert result.us_returns[3] == pytest.approx(
            _rising(date(2026, 10, 5)) / _rising(date(2026, 7, 3)) - 1
        )
        assert result.us_returns[6] == pytest.approx(
            _rising(date(2026, 10, 5)) / _rising(date(2026, 4, 3)) - 1
        )

    def test_risk_free_covers_the_trailing_windows(self):
        bars = _daily_bars(date(2025, 11, 1), date(2026, 10, 5))
        history_patch, rates_patch = self._patched(bars, bars, rates=_daily_rates(0.12))
        with history_patch, rates_patch:
            result = build_signal(RUN_DAY)

        assert result.rf_returns[1] == pytest.approx(0.01)
        assert result.rf_returns[6] == pytest.approx(1.01**6 - 1)
        assert result.signal == "VGIT"  # flat equities lose to the T-bill

    def test_fetch_windows_cover_the_six_month_lookback(self):
        bars = _daily_bars(date(2025, 11, 1), date(2026, 10, 5))
        history_patch, rates_patch = self._patched(bars, bars)
        with history_patch as mock_history, rates_patch as mock_rates:
            build_signal(RUN_DAY)

        for call in mock_history.call_args_list:
            _symbol, start, end = call.args
            assert start <= date(2026, 3, 27)  # well before the Apr 5 start
            assert end == RUN_DAY
        start, end = mock_rates.call_args.args
        assert start <= date(2026, 3, 27)
        assert end == RUN_DAY

    def test_one_history_fetch_per_symbol(self):
        bars = _daily_bars(date(2025, 11, 1), date(2026, 10, 5))
        history_patch, rates_patch = self._patched(bars, bars)
        with history_patch as mock_history, rates_patch:
            build_signal(RUN_DAY)

        assert mock_history.call_count == 2

    def test_lagging_series_sets_the_shared_anchor(self):
        us = _daily_bars(date(2025, 11, 1), date(2026, 10, 5), _rising)
        intl = _daily_bars(date(2025, 11, 1), date(2026, 10, 2))
        history_patch, rates_patch = self._patched(us, intl)
        with history_patch, rates_patch:
            result = build_signal(RUN_DAY)

        assert result.as_of == date(2026, 10, 2)
        assert result.us_returns[1] == pytest.approx(
            _rising(date(2026, 10, 2)) / _rising(date(2026, 9, 2)) - 1
        )


class TestBuildSignalMonthEnd:
    """Month-end (PV-parity) orchestration via `month_end=True`."""

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
            result = build_signal(TODAY, month_end=True)

        assert result.as_of == date(2026, 6, 30)
        assert result.us_returns[1] == pytest.approx(110.0 / 105.0 - 1)
        assert result.signal == "VOO"

    def test_uses_pv_tickers(self):
        history_patch, rates_patch = self._patched(
            [100.0] * 7, [50.0, 51.0, 52.0, 53.0, 54.0, 55.0, 60.0]
        )
        with history_patch as mock_history, rates_patch:
            result = build_signal(TODAY, month_end=True)

        assert sorted(call.args[0] for call in mock_history.call_args_list) == [
            "VOO",
            "VXUS",
        ]
        assert result.signal == "VXUS"

    def test_one_history_fetch_per_symbol(self):
        """Regression: credits budget. Exactly one price fetch per symbol."""
        history_patch, rates_patch = self._patched([100.0] * 7, [50.0] * 7)
        with history_patch as mock_history, rates_patch:
            build_signal(TODAY, month_end=True)

        assert mock_history.call_count == 2

    def test_fetches_enough_history_for_the_six_month_lookback(self):
        history_patch, rates_patch = self._patched([100.0] * 7, [50.0] * 7)
        with history_patch as mock_history, rates_patch:
            build_signal(TODAY, month_end=True)

        for call in mock_history.call_args_list:
            _symbol, start, end = call.args
            assert start <= date(2025, 12, 1)  # covers the Dec 2025 month end
            assert end == TODAY

    def test_fetches_rates_covering_the_risk_free_windows(self):
        history_patch, rates_patch = self._patched([100.0] * 7, [50.0] * 7)
        with history_patch, rates_patch as mock_rates:
            build_signal(TODAY, month_end=True)

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
            result = build_signal(TODAY, month_end=True)

        assert result.rf_returns[1] == pytest.approx(0.01)
        assert result.rf_returns[6] == pytest.approx(1.01**6 - 1)
        # Flat equities lose to a positive risk-free rate.
        assert result.signal == "VGIT"

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
            result = build_signal(date(2026, 7, 31), month_end=True)

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

        main(today=TODAY, argv=["--month-end"])

        output = capsys.readouterr().out
        assert "VOO:" in output
        assert "VXUS:" in output
        assert "1-Month" in output
        assert "2026-06-30" in output
        assert re.search(r"^Signal: VOO\b", output, re.MULTILINE)

    @patch("dm.cli.get_tbill_rates", return_value=_daily_rates())
    @patch("dm.cli.get_price_history")
    def test_defaults_to_today(self, mock_history, _mock_rates, capsys):
        mock_history.side_effect = lambda symbol, start, end: _daily_bars(start, end)

        with patch("dm.cli.session_date", return_value=date(2026, 10, 5)):
            main(argv=[])

        _symbol, _start, end = mock_history.call_args.args
        assert end == date(2026, 10, 5)
        assert "Signal:" in capsys.readouterr().out

    @patch("dm.cli.get_tbill_rates", return_value=_daily_rates())
    @patch("dm.cli.get_price_history")
    def test_default_reports_trailing_windows_at_the_latest_close(
        self, mock_history, _mock_rates, capsys
    ):
        mock_history.side_effect = lambda symbol, start, end: _daily_bars(
            date(2025, 11, 1),
            date(2026, 10, 5),
            _rising if symbol == US_TICKER else lambda d: 50.0,
        )

        main(today=RUN_DAY, argv=[])

        output = capsys.readouterr().out
        assert "As of: 2026-10-05 (latest close, trailing windows)" in output
        assert "Windows from: 1M 2026-09-05, 3M 2026-07-05, 6M 2026-04-05" in output
        assert re.search(r"^Signal: VOO \(as of 2026-10-05\)", output, re.MULTILINE)

    @patch("dm.cli.get_tbill_rates", return_value=_rates())
    @patch("dm.cli.get_price_history")
    def test_month_end_flag_keeps_the_month_end_anchor(
        self, mock_history, _mock_rates, capsys
    ):
        mock_history.side_effect = lambda symbol, start, end: _bars(
            [100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 110.0]
            if symbol == US_TICKER
            else [50.0] * 7
        )

        main(today=TODAY, argv=["--month-end"])

        output = capsys.readouterr().out
        assert "As of: 2026-06-30 (month-end close)" in output
        assert re.search(r"^Signal: VOO \(hold from 2026-06-30\)", output, re.M)

    def test_now_flag_is_gone(self):
        """Trailing is the default now; the old month-end-based --now preview
        would silently report partial-month returns."""
        with pytest.raises(SystemExit):
            main(today=TODAY, argv=["--now"])

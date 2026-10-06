"""Tests for the PV-parity signal engine."""

from datetime import date, timedelta

import pytest

from dm.signals import (
    WEIGHTS,
    SignalResult,
    accumulate_rf_returns,
    anchor_latest,
    anchor_month_end,
    compute_signal,
    compute_signal_trailing,
    is_month_end_anchor,
    lookback_dates,
    month_end_closes,
    trailing_rf_returns,
    weighted_score,
)

# Month-end closes used by most compute_signal tests: Dec 2025 .. Jun 2026.
_MONTH_ENDS = [
    date(2025, 12, 31),
    date(2026, 1, 30),
    date(2026, 2, 27),
    date(2026, 3, 31),
    date(2026, 4, 30),
    date(2026, 5, 29),
    date(2026, 6, 30),
]


def _series(closes: list[float]) -> list[tuple[date, float]]:
    """Build a month-end bar series from 7 closes (Dec 2025 .. Jun 2026)."""
    return list(zip(_MONTH_ENDS, closes))


class TestWeights:
    """The PV momentum weights are 33% / 33% / 34%."""

    def test_weights_are_pv_values(self):
        assert WEIGHTS == {1: 0.33, 3: 0.33, 6: 0.34}

    def test_weights_sum_to_one(self):
        assert sum(WEIGHTS.values()) == pytest.approx(1.0)


class TestWeightedScore:
    """Tests for `weighted_score`."""

    def test_applies_pv_weights(self):
        score = weighted_score({1: 0.10, 3: 0.20, 6: 0.30})
        assert score == pytest.approx(0.33 * 0.10 + 0.33 * 0.20 + 0.34 * 0.30)

    def test_equal_returns_give_same_score(self):
        assert weighted_score({1: 0.05, 3: 0.05, 6: 0.05}) == pytest.approx(0.05)

    def test_six_month_leg_is_weighted_heaviest(self):
        heavy_6m = weighted_score({1: 0.0, 3: 0.0, 6: 0.10})
        heavy_1m = weighted_score({1: 0.10, 3: 0.0, 6: 0.0})
        assert heavy_6m > heavy_1m

    def test_handles_negative_returns(self):
        score = weighted_score({1: -0.02, 3: -0.05, 6: 0.01})
        assert score == pytest.approx(0.33 * -0.02 + 0.33 * -0.05 + 0.34 * 0.01)


class TestMonthEndCloses:
    """Tests for reducing daily bars to the last bar of each calendar month."""

    def test_returns_last_bar_of_each_month(self):
        bars = [
            (date(2026, 1, 2), 100.0),
            (date(2026, 1, 30), 101.0),
            (date(2026, 2, 2), 102.0),
            (date(2026, 2, 27), 103.0),
            (date(2026, 3, 31), 104.0),
        ]

        assert month_end_closes(bars) == [
            (date(2026, 1, 30), 101.0),
            (date(2026, 2, 27), 103.0),
            (date(2026, 3, 31), 104.0),
        ]

    def test_sorts_unordered_input(self):
        bars = [
            (date(2026, 2, 27), 103.0),
            (date(2026, 1, 30), 101.0),
            (date(2026, 1, 2), 100.0),
        ]

        assert month_end_closes(bars) == [
            (date(2026, 1, 30), 101.0),
            (date(2026, 2, 27), 103.0),
        ]

    def test_single_bar_month(self):
        bars = [(date(2026, 1, 30), 101.0)]
        assert month_end_closes(bars) == [(date(2026, 1, 30), 101.0)]

    def test_empty_input(self):
        assert month_end_closes([]) == []

    def test_spans_year_boundary(self):
        bars = [
            (date(2025, 12, 30), 90.0),
            (date(2025, 12, 31), 91.0),
            (date(2026, 1, 2), 92.0),
        ]

        assert month_end_closes(bars) == [
            (date(2025, 12, 31), 91.0),
            (date(2026, 1, 2), 92.0),
        ]


class TestAnchorMonthEnd:
    """The anchor is the last bar of the most recent COMPLETED calendar month."""

    def _july_bars(self):
        return [
            (date(2026, 5, 29), 100.0),
            (date(2026, 6, 29), 101.0),
            (date(2026, 6, 30), 102.0),
            (date(2026, 7, 1), 103.0),
            (date(2026, 7, 24), 104.0),
        ]

    def test_mid_month_anchors_on_prior_month_end(self):
        assert anchor_month_end(self._july_bars(), date(2026, 7, 15)) == (
            date(2026, 6, 30),
            102.0,
        )

    def test_last_calendar_day_anchors_on_current_month(self):
        """Running on July 31 anchors on July's last available trading bar."""
        assert anchor_month_end(self._july_bars(), date(2026, 7, 31)) == (
            date(2026, 7, 24),
            104.0,
        )

    def test_day_before_month_end_still_anchors_on_prior_month(self):
        assert anchor_month_end(self._july_bars(), date(2026, 7, 30)) == (
            date(2026, 6, 30),
            102.0,
        )

    def test_first_of_month_anchors_on_prior_month(self):
        assert anchor_month_end(self._july_bars(), date(2026, 7, 1)) == (
            date(2026, 6, 30),
            102.0,
        )

    def test_raises_when_no_completed_month(self):
        bars = [(date(2026, 7, 1), 100.0), (date(2026, 7, 24), 104.0)]

        with pytest.raises(ValueError, match="completed month"):
            anchor_month_end(bars, date(2026, 7, 15))

    def test_raises_on_empty_bars(self):
        with pytest.raises(ValueError):
            anchor_month_end([], date(2026, 7, 15))


class TestAccumulateRfReturns:
    """Risk-free windows compound monthly rates lagged one month."""

    def _flat_rates(self, annual: float):
        return [(d, annual) for d in _MONTH_ENDS]

    def test_flat_rate_compounds_over_window(self):
        rf = accumulate_rf_returns(self._flat_rates(0.06), date(2026, 6, 30))

        assert rf[1] == pytest.approx(0.005)
        assert rf[3] == pytest.approx(1.005**3 - 1)
        assert rf[6] == pytest.approx(1.005**6 - 1)

    def test_returns_all_three_windows(self):
        rf = accumulate_rf_returns(self._flat_rates(0.04), date(2026, 6, 30))
        assert set(rf) == {1, 3, 6}

    def test_uses_prior_month_end_rate(self):
        """Month m's return uses the rate at the end of month m-1.

        Only December 2025's rate is non-zero, so it can only show up in the
        6-month window (whose first month is January 2026).
        """
        rates = dict.fromkeys(_MONTH_ENDS, 0.0)
        rates[date(2025, 12, 31)] = 0.12
        rates[date(2026, 6, 30)] = 0.24  # anchor month rate is never used

        rf = accumulate_rf_returns(sorted(rates.items()), date(2026, 6, 30))

        assert rf[1] == pytest.approx(0.0)
        assert rf[3] == pytest.approx(0.0)
        assert rf[6] == pytest.approx(0.01)

    def test_uses_last_observation_of_each_month(self):
        """A daily series collapses to the last observation in each month."""
        rates = [(d, 0.0) for d in _MONTH_ENDS if d != date(2026, 5, 29)]
        rates.append((date(2026, 5, 1), 0.99))  # early-May noise, must be ignored
        rates.append((date(2026, 5, 29), 0.12))  # the May month-end observation
        rates.sort()

        rf = accumulate_rf_returns(rates, date(2026, 6, 30))

        assert rf[1] == pytest.approx(0.01)

    def test_falls_back_to_most_recent_prior_observation(self):
        """A month with no observation reuses the latest earlier rate."""
        rates = [(d, 0.12) for d in _MONTH_ENDS if d != date(2026, 5, 29)]

        rf = accumulate_rf_returns(rates, date(2026, 6, 30))

        assert rf[1] == pytest.approx(0.01)

    def test_anchor_may_be_any_date_in_the_anchor_month(self):
        flat = self._flat_rates(0.06)
        assert accumulate_rf_returns(flat, date(2026, 6, 1)) == pytest.approx(
            accumulate_rf_returns(flat, date(2026, 6, 30))
        )

    def test_zero_rates_give_zero_returns(self):
        rf = accumulate_rf_returns(self._flat_rates(0.0), date(2026, 6, 30))
        assert rf == {
            1: pytest.approx(0.0),
            3: pytest.approx(0.0),
            6: pytest.approx(0.0),
        }

    def test_raises_when_history_too_short(self):
        rates = [(date(2026, 5, 29), 0.05), (date(2026, 6, 30), 0.05)]

        with pytest.raises(ValueError, match="risk-free"):
            accumulate_rf_returns(rates, date(2026, 6, 30))


class TestComputeSignal:
    """Tests for the dual-momentum decision rule."""

    RF_FLAT = {1: 0.001, 3: 0.003, 6: 0.006}

    def test_returns_signal_result(self):
        result = compute_signal(
            _series([100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 110.0]),
            _series([50.0] * 7),
            self.RF_FLAT,
            date(2026, 7, 15),
        )

        assert isinstance(result, SignalResult)
        assert result.as_of == date(2026, 6, 30)

    def test_month_end_to_month_end_returns(self):
        result = compute_signal(
            _series([100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 110.0]),
            _series([50.0] * 7),
            self.RF_FLAT,
            date(2026, 7, 15),
        )

        assert result.us_returns[1] == pytest.approx(110.0 / 105.0 - 1)
        assert result.us_returns[3] == pytest.approx(110.0 / 103.0 - 1)
        assert result.us_returns[6] == pytest.approx(110.0 / 100.0 - 1)
        assert result.intl_returns == {
            1: pytest.approx(0.0),
            3: pytest.approx(0.0),
            6: pytest.approx(0.0),
        }

    def test_scores_use_weighted_score(self):
        result = compute_signal(
            _series([100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 110.0]),
            _series([50.0] * 7),
            self.RF_FLAT,
            date(2026, 7, 15),
        )

        assert result.us_score == pytest.approx(weighted_score(result.us_returns))
        assert result.intl_score == pytest.approx(weighted_score(result.intl_returns))
        assert result.rf_score == pytest.approx(weighted_score(self.RF_FLAT))
        assert result.rf_returns == self.RF_FLAT

    def test_us_wins_relative_momentum(self):
        result = compute_signal(
            _series([100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 110.0]),
            _series([50.0] * 7),
            self.RF_FLAT,
            date(2026, 7, 15),
        )

        assert result.relative_winner == "VOO"
        assert result.signal == "VOO"

    def test_intl_wins_relative_momentum(self):
        result = compute_signal(
            _series([100.0] * 7),
            _series([50.0, 51.0, 52.0, 53.0, 54.0, 55.0, 60.0]),
            self.RF_FLAT,
            date(2026, 7, 15),
        )

        assert result.relative_winner == "VXUS"
        assert result.signal == "VXUS"

    def test_absolute_momentum_sends_signal_to_bond_fund(self):
        """Both equity scores below the risk-free score => hold the bond fund."""
        result = compute_signal(
            _series([100.0, 99.0, 98.0, 97.0, 96.0, 95.0, 90.0]),
            _series([50.0, 49.0, 48.0, 47.0, 46.0, 45.0, 40.0]),
            self.RF_FLAT,
            date(2026, 7, 15),
        )

        assert result.relative_winner == "VOO"
        assert result.us_score > result.intl_score
        assert result.us_score < result.rf_score
        assert result.signal == "VGIT"

    def test_positive_but_sub_risk_free_winner_goes_to_bonds(self):
        """Absolute momentum is measured against the risk-free rate, not zero."""
        rf = {1: 0.05, 3: 0.05, 6: 0.05}
        result = compute_signal(
            _series([100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 101.0]),
            _series([50.0] * 7),
            rf,
            date(2026, 7, 15),
        )

        assert result.us_score > 0
        assert result.signal == "VGIT"

    def test_winner_equal_to_risk_free_stays_in_equities(self):
        """Switch only on strictly negative excess return."""
        us = _series([100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 110.0])
        flat_return = 110.0 / 100.0 - 1
        rf = {1: flat_return, 3: flat_return, 6: flat_return}

        result = compute_signal(us, _series([50.0] * 7), rf, date(2026, 7, 15))

        assert result.us_score == pytest.approx(result.rf_score)
        assert result.signal == "VOO"

    def test_equity_tie_prefers_us(self):
        result = compute_signal(
            _series([100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 110.0]),
            _series([100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 110.0]),
            self.RF_FLAT,
            date(2026, 7, 15),
        )

        assert result.us_score == pytest.approx(result.intl_score)
        assert result.relative_winner == "VOO"
        assert result.signal == "VOO"

    def test_ignores_intra_month_bars(self):
        """Only month-end closes matter; mid-month noise must not move the score."""
        clean = _series([100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 110.0])
        noisy = sorted(
            clean
            + [
                (date(2026, 6, 15), 999.0),
                (date(2026, 5, 4), 1.0),
                (date(2026, 1, 5), 500.0),
            ]
        )

        noisy_result = compute_signal(
            noisy, _series([50.0] * 7), self.RF_FLAT, date(2026, 7, 15)
        )
        clean_result = compute_signal(
            clean, _series([50.0] * 7), self.RF_FLAT, date(2026, 7, 15)
        )

        assert noisy_result.us_returns == clean_result.us_returns
        assert noisy_result.as_of == clean_result.as_of

    def test_uses_latest_completed_month_when_run_at_month_end(self):
        us = _series([100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 110.0])
        us_with_july = us + [(date(2026, 7, 31), 121.0)]
        intl_with_july = _series([50.0] * 7) + [(date(2026, 7, 31), 50.0)]

        result = compute_signal(
            us_with_july, intl_with_july, self.RF_FLAT, date(2026, 7, 31)
        )

        assert result.as_of == date(2026, 7, 31)
        assert result.us_returns[1] == pytest.approx(121.0 / 110.0 - 1)

    def test_anchors_both_series_on_the_same_month(self):
        """If one series lags, both are anchored on the latest common month."""
        us = _series([100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 110.0])
        us_with_july = us + [(date(2026, 7, 31), 121.0)]
        intl = _series([50.0] * 7)  # no July bar

        result = compute_signal(us_with_july, intl, self.RF_FLAT, date(2026, 7, 31))

        assert result.as_of == date(2026, 6, 30)
        assert result.us_returns[1] == pytest.approx(110.0 / 105.0 - 1)

    def test_custom_tickers(self):
        result = compute_signal(
            _series([100.0, 99.0, 98.0, 97.0, 96.0, 95.0, 90.0]),
            _series([50.0] * 7),
            self.RF_FLAT,
            date(2026, 7, 15),
            us_ticker="VFINX",
            intl_ticker="VGTSX",
            bond_ticker="VFITX",
        )

        assert result.relative_winner == "VGTSX"
        assert result.signal == "VFITX"

    def test_result_is_frozen(self):
        result = compute_signal(
            _series([100.0] * 7), _series([50.0] * 7), self.RF_FLAT, date(2026, 7, 15)
        )

        with pytest.raises(Exception):
            result.signal = "VXUS"

    def test_raises_when_history_too_short(self):
        short = list(zip(_MONTH_ENDS[3:], [100.0, 101.0, 102.0, 103.0]))

        with pytest.raises(ValueError, match="2025-12"):
            compute_signal(short, short, self.RF_FLAT, date(2026, 7, 15))


# Sparse bars for the anchor_latest tests: month ends Dec 2025 .. Jun 2026 plus
# a handful of intra-month bars.
_SPARSE_BARS = [
    (date(2025, 12, 24), 99.5),
    (date(2025, 12, 31), 100.0),
    (date(2026, 1, 23), 100.5),
    (date(2026, 1, 30), 101.0),
    (date(2026, 2, 27), 102.0),
    (date(2026, 3, 31), 103.0),
    (date(2026, 4, 24), 103.5),
    (date(2026, 4, 30), 104.0),
    (date(2026, 5, 29), 105.0),
    (date(2026, 6, 24), 106.0),
    (date(2026, 6, 30), 107.0),
    (date(2026, 7, 24), 112.0),
]

_SPARSE_TODAY = date(2026, 7, 26)


class TestAnchorLatest:
    """The trailing anchor is simply the latest bar on or before today."""

    def test_picks_latest_bar_on_or_before_today(self):
        assert anchor_latest(_SPARSE_BARS, _SPARSE_TODAY) == (date(2026, 7, 24), 112.0)

    def test_picks_todays_bar_when_present(self):
        bars = _SPARSE_BARS + [(date(2026, 7, 26), 113.0)]
        assert anchor_latest(bars, _SPARSE_TODAY) == (date(2026, 7, 26), 113.0)

    def test_ignores_bars_after_today(self):
        bars = _SPARSE_BARS + [(date(2026, 7, 27), 999.0)]
        assert anchor_latest(bars, _SPARSE_TODAY) == (date(2026, 7, 24), 112.0)

    def test_sorts_unordered_input(self):
        assert anchor_latest(list(reversed(_SPARSE_BARS)), _SPARSE_TODAY) == (
            date(2026, 7, 24),
            112.0,
        )

    def test_raises_when_no_bar_on_or_before_today(self):
        with pytest.raises(ValueError, match="on or before"):
            anchor_latest(_SPARSE_BARS, date(2025, 12, 20))

    def test_raises_on_empty_bars(self):
        with pytest.raises(ValueError):
            anchor_latest([], _SPARSE_TODAY)


def _weekday_bars(
    start: date, end: date, price=lambda day: 100.0 + day.toordinal() % 1000
) -> list[tuple[date, float]]:
    """One bar per weekday from `start` to `end` inclusive."""
    bars = []
    day = start
    while day <= end:
        if day.weekday() < 5:
            bars.append((day, price(day)))
        day += timedelta(days=1)
    return bars


def _close_on(bars: list[tuple[date, float]], day: date) -> float:
    return dict(bars)[day]


def _flat_rates(annual: float, start: date = date(2025, 12, 1)):
    return [(d, annual) for d, _ in _weekday_bars(start, date(2026, 12, 31))]


class TestLookbackDates:
    """Window start dates: same calendar day N months back, or month ends."""

    def test_mid_month_steps_back_whole_calendar_months(self):
        assert lookback_dates(date(2026, 10, 5), month_end=False) == {
            1: date(2026, 9, 5),
            2: date(2026, 8, 5),
            3: date(2026, 7, 5),
            4: date(2026, 6, 5),
            5: date(2026, 5, 5),
            6: date(2026, 4, 5),
        }

    def test_clamps_to_shorter_months(self):
        dates = lookback_dates(date(2026, 8, 29), month_end=False)
        assert dates[6] == date(2026, 2, 28)
        assert dates[5] == date(2026, 3, 29)

    def test_month_end_steps_back_to_prior_month_ends(self):
        """Sep 30 - 1 month must be Aug 31, not Aug 30."""
        assert lookback_dates(date(2026, 9, 30), month_end=True) == {
            1: date(2026, 8, 31),
            2: date(2026, 7, 31),
            3: date(2026, 6, 30),
            4: date(2026, 5, 31),
            5: date(2026, 4, 30),
            6: date(2026, 3, 31),
        }

    def test_month_end_works_from_last_trading_day(self):
        """Friday Oct 30 closes October; the bases are September's etc. ends."""
        dates = lookback_dates(date(2026, 10, 30), month_end=True)
        assert dates[1] == date(2026, 9, 30)
        assert dates[3] == date(2026, 7, 31)
        assert dates[6] == date(2026, 4, 30)


class TestIsMonthEndAnchor:
    """An anchor counts as a month end once nothing else can trade that month."""

    def test_mid_month_is_not_a_month_end(self):
        assert not is_month_end_anchor(date(2026, 10, 5), date(2026, 10, 6))

    def test_completed_month_is_a_month_end(self):
        assert is_month_end_anchor(date(2026, 9, 30), date(2026, 10, 6))

    def test_last_calendar_day_is_a_month_end(self):
        assert is_month_end_anchor(date(2026, 7, 31), date(2026, 7, 31))

    def test_last_weekday_before_a_weekend_month_end(self):
        """Fri Oct 30 2026 is October's last weekday (Oct 31 is a Saturday)."""
        assert is_month_end_anchor(date(2026, 10, 30), date(2026, 10, 30))

    def test_earlier_weekday_is_not_a_month_end(self):
        assert not is_month_end_anchor(date(2026, 10, 29), date(2026, 10, 30))

    def test_memorial_day_month_end(self):
        """Mon May 31 2027 is Memorial Day: Fri May 28 is May's final close."""
        assert is_month_end_anchor(date(2027, 5, 28), date(2027, 5, 29))

    def test_good_friday_month_end(self):
        """Fri Mar 29 2024 is Good Friday: Thu Mar 28 is March's final close."""
        assert is_month_end_anchor(date(2024, 3, 28), date(2024, 3, 28))

    def test_day_before_a_holiday_mid_month_is_not_a_month_end(self):
        """Thu Apr 2 2026 precedes Good Friday Apr 3, but April trades on."""
        assert not is_month_end_anchor(date(2026, 4, 2), date(2026, 4, 3))

    def test_holiday_month_end_once_the_month_is_over(self):
        """Good Friday 2024-03-29: Thu Mar 28 was March's final close."""
        assert is_month_end_anchor(date(2024, 3, 28), date(2024, 4, 1))

    def test_not_a_month_end_when_a_later_bar_exists_that_month(self):
        """Another series trading after the anchor proves the month went on."""
        later = [(date(2026, 9, 30), 1.0)]
        assert not is_month_end_anchor(date(2026, 9, 29), date(2026, 10, 1), later)

    def test_later_bars_in_other_months_do_not_count(self):
        later = [(date(2026, 10, 1), 1.0)]
        assert is_month_end_anchor(date(2026, 9, 30), date(2026, 10, 1), later)


class TestTrailingRfReturns:
    """Each one-month sub-window earns the rate observed at its start / 12."""

    def test_flat_rate_compounds_over_window(self):
        rf = trailing_rf_returns(
            _flat_rates(0.06), lookback_dates(date(2026, 10, 5), month_end=False)
        )

        assert rf[1] == pytest.approx(0.005)
        assert rf[3] == pytest.approx(1.005**3 - 1)
        assert rf[6] == pytest.approx(1.005**6 - 1)

    def test_uses_rate_observed_at_each_sub_window_start(self):
        """Only the rate on or before Apr 5 feeds the 6th sub-window."""
        rates = [
            (d, 0.0) for d, _ in _weekday_bars(date(2026, 1, 1), date(2026, 10, 5))
        ]
        rates = [(d, 0.12 if d == date(2026, 4, 3) else r) for d, r in rates]

        rf = trailing_rf_returns(
            rates, lookback_dates(date(2026, 10, 5), month_end=False)
        )

        # Apr 5 2026 is a Sunday: the Friday Apr 3 observation is the latest.
        assert rf[1] == pytest.approx(0.0)
        assert rf[3] == pytest.approx(0.0)
        assert rf[6] == pytest.approx(0.01)

    def test_matches_month_end_accumulation_at_month_ends(self):
        rates = [
            (d, 0.03 + d.toordinal() % 17 / 1000)
            for d, _ in _weekday_bars(date(2025, 11, 1), date(2026, 7, 31))
        ]
        anchor = date(2026, 6, 30)

        assert trailing_rf_returns(
            rates, lookback_dates(anchor, month_end=True)
        ) == pytest.approx(accumulate_rf_returns(rates, anchor))

    def test_raises_when_history_too_short(self):
        rates = [(date(2026, 9, 1), 0.05)]

        with pytest.raises(ValueError, match="risk-free"):
            trailing_rf_returns(
                rates, lookback_dates(date(2026, 10, 5), month_end=False)
            )


# Weekday bars Dec 1 2025 .. Oct 5 2026 for the trailing-mode tests (run Oct 6).
_DAILY_US = _weekday_bars(date(2025, 12, 1), date(2026, 10, 5))
_DAILY_INTL = _weekday_bars(
    date(2025, 12, 1), date(2026, 10, 5), price=lambda d: 50.0 + d.toordinal() % 37
)
_TRAIL_TODAY = date(2026, 10, 6)


class TestComputeSignalTrailing:
    """Trailing 1/3/6-month returns ending at the latest close on run day."""

    RATES = _flat_rates(0.036)

    def test_anchors_on_latest_close(self):
        result = compute_signal_trailing(
            _DAILY_US, _DAILY_INTL, self.RATES, _TRAIL_TODAY
        )

        assert isinstance(result, SignalResult)
        assert result.as_of == date(2026, 10, 5)

    def test_returns_span_whole_trailing_months(self):
        """Oct 5 close against the Sep 4 (Sep 5 is a Saturday), Jul 3
        (Jul 5 is a Sunday) and Apr 3 (Apr 5 is a Sunday) closes."""
        result = compute_signal_trailing(
            _DAILY_US, _DAILY_INTL, self.RATES, _TRAIL_TODAY
        )
        anchor = _close_on(_DAILY_US, date(2026, 10, 5))

        assert result.us_returns[1] == pytest.approx(
            anchor / _close_on(_DAILY_US, date(2026, 9, 4)) - 1
        )
        assert result.us_returns[3] == pytest.approx(
            anchor / _close_on(_DAILY_US, date(2026, 7, 3)) - 1
        )
        assert result.us_returns[6] == pytest.approx(
            anchor / _close_on(_DAILY_US, date(2026, 4, 3)) - 1
        )

    def test_uses_the_exact_day_when_it_traded(self):
        result = compute_signal_trailing(
            _DAILY_US, _DAILY_INTL, self.RATES, date(2026, 9, 16)
        )
        anchor = _close_on(_DAILY_US, date(2026, 9, 16))

        assert result.us_returns[1] == pytest.approx(
            anchor / _close_on(_DAILY_US, date(2026, 8, 14)) - 1  # Aug 16 = Sun
        )
        assert result.us_returns[3] == pytest.approx(
            anchor / _close_on(_DAILY_US, date(2026, 6, 16)) - 1  # a Tuesday
        )

    def test_reports_window_start_dates(self):
        result = compute_signal_trailing(
            _DAILY_US, _DAILY_INTL, self.RATES, _TRAIL_TODAY
        )

        assert result.window_starts == {
            1: date(2026, 9, 5),
            3: date(2026, 7, 5),
            6: date(2026, 4, 5),
        }

    def test_risk_free_covers_the_same_trailing_windows(self):
        result = compute_signal_trailing(
            _DAILY_US, _DAILY_INTL, self.RATES, _TRAIL_TODAY
        )

        assert result.rf_returns[1] == pytest.approx(0.003)
        assert result.rf_returns[3] == pytest.approx(1.003**3 - 1)
        assert result.rf_returns[6] == pytest.approx(1.003**6 - 1)

    def test_scores_use_weighted_score(self):
        result = compute_signal_trailing(
            _DAILY_US, _DAILY_INTL, self.RATES, _TRAIL_TODAY
        )

        assert result.us_score == pytest.approx(weighted_score(result.us_returns))
        assert result.intl_score == pytest.approx(weighted_score(result.intl_returns))
        assert result.rf_score == pytest.approx(weighted_score(result.rf_returns))

    def test_ignores_bars_after_today(self):
        future = _DAILY_US + [(date(2026, 10, 7), 9999.0)]
        result = compute_signal_trailing(future, _DAILY_INTL, self.RATES, _TRAIL_TODAY)

        assert result.as_of == date(2026, 10, 5)

    @pytest.mark.parametrize(
        ("last_bar", "today"),
        [
            (date(2026, 6, 30), date(2026, 7, 1)),
            (date(2026, 7, 31), date(2026, 7, 31)),
            (date(2026, 9, 30), date(2026, 10, 1)),
            (date(2026, 9, 30), date(2026, 10, 4)),
        ],
    )
    def test_matches_month_end_mode_on_a_month_end_close(self, last_bar, today):
        """With a month's final close as the latest bar, the trailing signal is
        the PV month-end signal exactly."""
        us = [bar for bar in _DAILY_US if bar[0] <= last_bar]
        intl = [bar for bar in _DAILY_INTL if bar[0] <= last_bar]

        trailing = compute_signal_trailing(us, intl, self.RATES, today)
        month_end = compute_signal(
            us, intl, accumulate_rf_returns(self.RATES, trailing.as_of), today
        )

        assert trailing.as_of == month_end.as_of
        assert trailing.us_returns == pytest.approx(month_end.us_returns)
        assert trailing.intl_returns == pytest.approx(month_end.intl_returns)
        assert trailing.rf_returns == pytest.approx(month_end.rf_returns)
        assert trailing.signal == month_end.signal

    def test_last_weekday_of_month_uses_month_end_bases(self):
        """Fri Oct 30 2026 closes October, so the 3-month base is the Jul 31
        month end rather than the same-day Jul 30, and likewise Apr 30."""
        us = _weekday_bars(date(2026, 1, 2), date(2026, 10, 30))
        result = compute_signal_trailing(us, us, self.RATES, date(2026, 10, 30))
        anchor = _close_on(us, date(2026, 10, 30))

        assert result.us_returns[3] == pytest.approx(
            anchor / _close_on(us, date(2026, 7, 31)) - 1
        )
        assert result.us_returns[6] == pytest.approx(
            anchor / _close_on(us, date(2026, 4, 30)) - 1
        )

    def test_lagging_series_at_month_end_does_not_snap(self):
        """US has Sep 30, VXUS stops at Sep 29: the shared Sep 29 anchor is not
        September's final close, so the windows trail from the 29th."""
        us = [bar for bar in _DAILY_US if bar[0] <= date(2026, 9, 30)]
        intl = [bar for bar in _DAILY_INTL if bar[0] <= date(2026, 9, 29)]
        result = compute_signal_trailing(us, intl, self.RATES, date(2026, 10, 1))

        assert result.as_of == date(2026, 9, 29)
        assert result.window_starts == {
            1: date(2026, 8, 29),
            3: date(2026, 6, 29),
            6: date(2026, 3, 29),
        }

    def test_raises_on_a_stale_anchor(self):
        """Prices that stopped weeks ago must not pass for today's signal."""
        old = [bar for bar in _DAILY_US if bar[0] <= date(2026, 9, 18)]

        with pytest.raises(ValueError, match="stale"):
            compute_signal_trailing(old, old, self.RATES, _TRAIL_TODAY)

    def test_memorial_day_month_end_uses_month_end_bases(self):
        """Run Sat May 29 2027 on the Fri May 28 close: May is over in all but
        name (Mon May 31 is Memorial Day), so the windows start at month ends."""
        bars = _weekday_bars(date(2026, 10, 1), date(2027, 5, 28))
        rates = _flat_rates(0.036, start=date(2026, 10, 1))
        result = compute_signal_trailing(bars, bars, rates, date(2027, 5, 29))

        assert result.window_starts == {
            1: date(2027, 4, 30),
            3: date(2027, 2, 28),
            6: date(2026, 11, 30),
        }

    def test_anchors_both_series_on_the_same_date(self):
        """A lagging series pulls both onto its latest close."""
        intl = [bar for bar in _DAILY_INTL if bar[0] <= date(2026, 10, 2)]
        result = compute_signal_trailing(_DAILY_US, intl, self.RATES, _TRAIL_TODAY)

        assert result.as_of == date(2026, 10, 2)
        assert result.us_returns[1] == pytest.approx(
            _close_on(_DAILY_US, date(2026, 10, 2))
            / _close_on(_DAILY_US, date(2026, 9, 2))
            - 1
        )

    def test_shared_anchor_follows_a_lagging_us_series(self):
        us = [bar for bar in _DAILY_US if bar[0] <= date(2026, 10, 2)]
        result = compute_signal_trailing(us, _DAILY_INTL, self.RATES, _TRAIL_TODAY)

        assert result.as_of == date(2026, 10, 2)
        assert result.intl_returns[1] == pytest.approx(
            _close_on(_DAILY_INTL, date(2026, 10, 2))
            / _close_on(_DAILY_INTL, date(2026, 9, 2))
            - 1
        )

    def test_applies_dual_momentum_decision_rule(self):
        flat_us = [(d, 100.0) for d, _ in _DAILY_US]
        rising_intl = [(d, 50.0 + i * 0.1) for i, (d, _) in enumerate(_DAILY_US)]
        result = compute_signal_trailing(flat_us, rising_intl, self.RATES, _TRAIL_TODAY)

        assert result.relative_winner == "VXUS"
        assert result.signal == "VXUS"

    def test_absolute_momentum_sends_signal_to_bond_fund(self):
        flat_us = [(d, 100.0) for d, _ in _DAILY_US]
        falling = [(d, 50.0 - i * 0.01) for i, (d, _) in enumerate(_DAILY_US)]
        result = compute_signal_trailing(flat_us, falling, self.RATES, _TRAIL_TODAY)

        assert result.relative_winner == "VOO"
        assert result.signal == "VGIT"

    def test_custom_tickers(self):
        flat_us = [(d, 100.0) for d, _ in _DAILY_US]
        falling = [(d, 50.0 - i * 0.01) for i, (d, _) in enumerate(_DAILY_US)]
        result = compute_signal_trailing(
            flat_us,
            falling,
            self.RATES,
            _TRAIL_TODAY,
            us_ticker="VFINX",
            intl_ticker="VGTSX",
            bond_ticker="VFITX",
        )

        assert result.relative_winner == "VFINX"
        assert result.signal == "VFITX"

    def test_raises_when_history_too_short(self):
        short = [bar for bar in _DAILY_US if bar[0] >= date(2026, 5, 1)]

        with pytest.raises(ValueError, match="on or before 2026-04-05"):
            compute_signal_trailing(short, short, self.RATES, _TRAIL_TODAY)

    def test_raises_on_a_stale_base_close(self):
        """A data gap must not silently stretch a window by weeks."""
        gappy = [
            bar
            for bar in _DAILY_US
            if not date(2026, 6, 15) <= bar[0] <= date(2026, 7, 10)
        ]

        with pytest.raises(ValueError, match="stale"):
            compute_signal_trailing(gappy, gappy, self.RATES, _TRAIL_TODAY)

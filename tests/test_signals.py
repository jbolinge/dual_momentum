"""Tests for the PV-parity signal engine."""

from datetime import date

import pytest

from dm.signals import (
    WEIGHTS,
    SignalResult,
    accumulate_rf_returns,
    anchor_latest,
    anchor_month_end,
    compute_signal,
    compute_signal_now,
    month_end_closes,
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


# Daily-ish bars used by the --now tests: month ends Dec 2025 .. Jun 2026 plus
# a handful of intra-month bars near the date-shifted lookback targets.
_NOW_BARS = [
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

_NOW_TODAY = date(2026, 7, 26)


class TestAnchorLatest:
    """The --now anchor is simply the latest bar on or before today."""

    def test_picks_latest_bar_on_or_before_today(self):
        assert anchor_latest(_NOW_BARS, _NOW_TODAY) == (date(2026, 7, 24), 112.0)

    def test_picks_todays_bar_when_present(self):
        bars = _NOW_BARS + [(date(2026, 7, 26), 113.0)]
        assert anchor_latest(bars, _NOW_TODAY) == (date(2026, 7, 26), 113.0)

    def test_ignores_bars_after_today(self):
        bars = _NOW_BARS + [(date(2026, 7, 27), 999.0)]
        assert anchor_latest(bars, _NOW_TODAY) == (date(2026, 7, 24), 112.0)

    def test_sorts_unordered_input(self):
        assert anchor_latest(list(reversed(_NOW_BARS)), _NOW_TODAY) == (
            date(2026, 7, 24),
            112.0,
        )

    def test_raises_when_no_bar_on_or_before_today(self):
        with pytest.raises(ValueError, match="on or before"):
            anchor_latest(_NOW_BARS, date(2025, 12, 20))

    def test_raises_on_empty_bars(self):
        with pytest.raises(ValueError):
            anchor_latest([], _NOW_TODAY)


class TestComputeSignalNow:
    """--now evaluates the rule at the latest close instead of the month end."""

    RF_FLAT = {1: 0.001, 3: 0.003, 6: 0.006}

    def test_anchors_on_latest_bar(self):
        result = compute_signal_now(
            _NOW_BARS, [(d, 50.0) for d, _ in _NOW_BARS], self.RF_FLAT, _NOW_TODAY
        )

        assert isinstance(result, SignalResult)
        assert result.as_of == date(2026, 7, 24)

    def test_lookbacks_use_prior_month_end_bases(self):
        """Each leg divides the anchor close by a month-end close, exactly as
        the month-end mode would once the anchor's month completes."""
        result = compute_signal_now(
            _NOW_BARS, [(d, 50.0) for d, _ in _NOW_BARS], self.RF_FLAT, _NOW_TODAY
        )

        assert result.us_returns[1] == pytest.approx(112.0 / 107.0 - 1)  # Jun 30
        assert result.us_returns[3] == pytest.approx(112.0 / 104.0 - 1)  # Apr 30
        assert result.us_returns[6] == pytest.approx(112.0 / 101.0 - 1)  # Jan 30

    def test_intra_month_noise_never_feeds_the_bases(self):
        """Bases are month-end closes; mid-month bars only matter as the anchor."""
        noisy = sorted(_NOW_BARS + [(date(2026, 4, 15), 999.0)])
        clean = compute_signal_now(
            _NOW_BARS, [(d, 50.0) for d, _ in _NOW_BARS], self.RF_FLAT, _NOW_TODAY
        )
        result = compute_signal_now(
            noisy, [(d, 50.0) for d, _ in _NOW_BARS], self.RF_FLAT, _NOW_TODAY
        )

        assert result.us_returns == clean.us_returns

    def test_matches_month_end_mode_when_anchor_is_the_month_end(self):
        """Run on the month's final close, --now must reproduce the default
        signal exactly — same anchor, same bases, same decision."""
        bars = [bar for bar in _NOW_BARS if bar[0] <= date(2026, 6, 30)]
        intl = [(d, value / 2) for d, value in bars]
        today = date(2026, 7, 15)

        now_result = compute_signal_now(bars, intl, self.RF_FLAT, today)
        month_end_result = compute_signal(bars, intl, self.RF_FLAT, today)

        assert now_result == month_end_result

    def test_anchors_both_series_on_the_same_date(self):
        """If one series lags, both are priced at the shared latest date."""
        intl = [(d, 50.0) for d, _ in _NOW_BARS if d <= date(2026, 6, 30)]
        result = compute_signal_now(_NOW_BARS, intl, self.RF_FLAT, _NOW_TODAY)

        assert result.as_of == date(2026, 6, 30)
        assert result.us_returns[1] == pytest.approx(107.0 / 105.0 - 1)  # May 29

    def test_shared_anchor_follows_a_lagging_us_series(self):
        """The shared anchor is the earlier latest bar whichever series lags."""
        us = [bar for bar in _NOW_BARS if bar[0] <= date(2026, 6, 30)]
        intl = [(d, value / 2) for d, value in _NOW_BARS]  # has the July 24 bar
        result = compute_signal_now(us, intl, self.RF_FLAT, _NOW_TODAY)

        assert result.as_of == date(2026, 6, 30)
        # The leading series is priced at its close on or before the shared
        # anchor, not at its own later bar.
        assert result.intl_returns[1] == pytest.approx(53.5 / 52.5 - 1)

    def test_applies_dual_momentum_decision_rule(self):
        flat_us = [(d, 100.0) for d, _ in _NOW_BARS]
        rising_intl = [(d, value / 2) for d, value in _NOW_BARS]
        result = compute_signal_now(flat_us, rising_intl, self.RF_FLAT, _NOW_TODAY)

        assert result.relative_winner == "VXUS"
        assert result.signal == "VXUS"

    def test_absolute_momentum_sends_signal_to_bond_fund(self):
        falling = [(d, 200.0 - value) for d, value in _NOW_BARS]
        flat_intl = [(d, 50.0 - 0.01 * index) for index, (d, _) in enumerate(_NOW_BARS)]
        result = compute_signal_now(falling, flat_intl, self.RF_FLAT, _NOW_TODAY)

        assert result.signal == "VGIT"

    def test_custom_tickers(self):
        result = compute_signal_now(
            _NOW_BARS,
            [(d, 50.0) for d, _ in _NOW_BARS],
            self.RF_FLAT,
            _NOW_TODAY,
            us_ticker="VFINX",
            intl_ticker="VGTSX",
            bond_ticker="VFITX",
        )

        assert result.relative_winner == "VFINX"
        assert result.signal == "VFINX"

    def test_custom_bond_ticker_on_absolute_momentum_failure(self):
        falling = [(d, 200.0 - value) for d, value in _NOW_BARS]
        flat_intl = [(d, 50.0 - 0.01 * index) for index, (d, _) in enumerate(_NOW_BARS)]
        result = compute_signal_now(
            falling,
            flat_intl,
            self.RF_FLAT,
            _NOW_TODAY,
            us_ticker="VFINX",
            intl_ticker="VGTSX",
            bond_ticker="VFITX",
        )

        assert result.signal == "VFITX"

    def test_raises_when_history_too_short(self):
        short = [bar for bar in _NOW_BARS if bar[0] >= date(2026, 3, 1)]

        with pytest.raises(ValueError, match="2026-01"):
            compute_signal_now(short, short, self.RF_FLAT, _NOW_TODAY)

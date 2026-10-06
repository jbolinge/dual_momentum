"""Integration tests that call real external APIs.

Run with: uv run pytest -m integration
Skip with: uv run pytest -m "not integration"
"""

import os
import subprocess
from datetime import date

import pytest
import yfinance as yf
from dateutil.relativedelta import relativedelta
from dotenv import load_dotenv

from dm.cli import BOND_TICKER, INTL_TICKER, US_TICKER, build_signal
from dm.data import _get_price_history_twelvedata, get_price_history, get_tbill_rates
from dm.signals import month_end_closes

pytestmark = pytest.mark.integration


class TestTwelveDataIntegration:
    """Integration tests for the TwelveData fetcher (skipped if no API key)."""

    def setup_method(self):
        load_dotenv()
        if not os.getenv("TWELVEDATA_API_KEY"):
            pytest.skip("TWELVEDATA_API_KEY not set")

    def test_returns_six_months_of_bars(self):
        end = date.today()
        bars = _get_price_history_twelvedata("VOO", end - relativedelta(months=6), end)

        assert len(bars) > 100
        assert all(100 < close < 2000 for _, close in bars)

    def test_closes_are_dividend_adjusted(self):
        """TwelveData's default `adjust=splits` omits dividends; we ask for `all`.

        The check is a real 6-month VXUS return against yfinance's
        `auto_adjust=True` series over the same trading days — an unadjusted
        series is off by tens of basis points, far outside this tolerance.
        """
        end = date.today() - relativedelta(days=5)
        start = end - relativedelta(months=6)

        td_bars = dict(_get_price_history_twelvedata(INTL_TICKER, start, end))
        history = yf.Ticker(INTL_TICKER).history(start=start, end=end, auto_adjust=True)
        history.index = history.index.tz_localize(None)
        yf_bars = {
            ts.date(): float(c) for ts, c in zip(history.index, history["Close"])
        }

        common = sorted(set(td_bars) & set(yf_bars))
        assert len(common) > 100

        td_return = td_bars[common[-1]] / td_bars[common[0]] - 1
        yf_return = yf_bars[common[-1]] / yf_bars[common[0]] - 1

        assert td_return == pytest.approx(yf_return, abs=0.0015)


class TestPriceHistoryIntegration:
    """Integration tests for the price history fetcher (either source)."""

    def test_six_months_of_month_end_closes(self):
        end = date.today()
        bars = get_price_history(US_TICKER, end - relativedelta(months=8), end)
        month_ends = month_end_closes(bars)

        assert len(month_ends) >= 7
        assert month_ends == sorted(month_ends)


class TestFREDIntegration:
    """Integration tests for FRED API data fetching."""

    def test_get_tbill_rates(self):
        end = date.today()
        rates = get_tbill_rates(end - relativedelta(months=12), end)

        assert len(rates) > 200  # daily series
        assert rates == sorted(rates)
        assert all(0 <= rate <= 0.15 for _, rate in rates)


class TestSignalIntegration:
    """The full fetch-and-compute path against live data."""

    def test_build_signal_returns_a_tradeable_ticker(self):
        result = build_signal(date.today())

        today = date.today()

        assert result.signal in {US_TICKER, INTL_TICKER, BOND_TICKER}
        assert result.relative_winner in {US_TICKER, INTL_TICKER}
        # The trailing anchor is the latest close: within a long weekend.
        assert today - relativedelta(days=6) <= result.as_of <= today
        assert result.window_starts[1] >= today - relativedelta(months=1, days=6)
        for returns in (result.us_returns, result.intl_returns, result.rf_returns):
            assert set(returns) == {1, 3, 6}

    def test_month_end_build_signal_anchors_on_a_month_end(self):
        result = build_signal(date.today(), month_end=True)

        today = date.today()

        assert result.signal in {US_TICKER, INTL_TICKER, BOND_TICKER}
        # The anchor is a recent month end, never in the future.
        assert today - relativedelta(months=2) < result.as_of <= today
        for returns in (result.us_returns, result.intl_returns, result.rf_returns):
            assert set(returns) == {1, 3, 6}


class TestCLIIntegration:
    """Integration tests for the full CLI."""

    def _run(self):
        return subprocess.run(
            ["uv", "run", "dm"],
            capture_output=True,
            text=True,
            timeout=120,
        )

    def test_cli_runs_successfully(self):
        result = self._run()

        assert result.returncode == 0
        assert "Dual Momentum Analysis" in result.stdout
        assert f"{US_TICKER}:" in result.stdout
        assert f"{INTL_TICKER}:" in result.stdout
        assert "T-bill" in result.stdout

    def test_cli_output_structure(self):
        result = self._run()
        output = result.stdout

        assert "As of:" in output
        assert "1-Month:" in output
        assert "3-Month:" in output
        assert "6-Month:" in output
        assert "Score:" in output
        assert "Relative momentum:" in output
        assert "Absolute momentum:" in output

        signal_lines = [
            line for line in output.splitlines() if line.startswith("Signal: ")
        ]
        assert len(signal_lines) == 1
        assert signal_lines[0].split()[1] in {US_TICKER, INTL_TICKER, BOND_TICKER}

"""Tests for data fetching."""

from datetime import date
from unittest.mock import Mock, patch

import pandas as pd
import pytest
import requests

from dm.data import (
    _get_price_history_twelvedata,
    _get_price_history_yfinance,
    get_price_history,
    get_tbill_rates,
)


class TestGetTBillRates:
    """Tests for `get_tbill_rates` — the FRED DTB3 3-month T-bill series."""

    def _patched_fred(self, mock_fred_class, series):
        mock_fred = Mock()
        mock_fred_class.return_value = mock_fred
        mock_fred.get_series.return_value = series
        return mock_fred

    @patch("dm.data.Fred")
    @patch("dm.data.load_dotenv")
    @patch("dm.data.os.getenv")
    def test_returns_dated_decimal_rates(
        self, mock_getenv, _mock_load_dotenv, mock_fred_class
    ):
        mock_getenv.return_value = "fake_api_key"
        self._patched_fred(
            mock_fred_class,
            pd.Series(
                [5.25, 5.30, 5.28],
                index=pd.to_datetime(["2024-01-08", "2024-01-09", "2024-01-10"]),
            ),
        )

        rates = get_tbill_rates(date(2024, 1, 1), date(2024, 1, 10))

        assert rates == [
            (date(2024, 1, 8), pytest.approx(0.0525)),
            (date(2024, 1, 9), pytest.approx(0.0530)),
            (date(2024, 1, 10), pytest.approx(0.0528)),
        ]

    @patch("dm.data.Fred")
    @patch("dm.data.load_dotenv")
    @patch("dm.data.os.getenv")
    def test_requests_dtb3_over_the_window(
        self, mock_getenv, _mock_load_dotenv, mock_fred_class
    ):
        """PV's risk-free benchmark is the 3-month T-bill, not the 1-month."""
        mock_getenv.return_value = "fake_api_key"
        mock_fred = self._patched_fred(
            mock_fred_class,
            pd.Series([5.25], index=pd.to_datetime(["2024-01-10"])),
        )

        get_tbill_rates(date(2023, 6, 1), date(2024, 1, 10))

        args, _kwargs = mock_fred.get_series.call_args
        assert args[0] == "DTB3"
        assert args[1] == date(2023, 6, 1)
        assert args[2] == date(2024, 1, 10)

    @patch("dm.data.Fred")
    @patch("dm.data.load_dotenv")
    @patch("dm.data.os.getenv")
    def test_drops_nan_observations(
        self, mock_getenv, _mock_load_dotenv, mock_fred_class
    ):
        """FRED marks market holidays as NaN."""
        mock_getenv.return_value = "fake_api_key"
        self._patched_fred(
            mock_fred_class,
            pd.Series(
                [5.25, float("nan"), 5.28],
                index=pd.to_datetime(["2024-01-08", "2024-01-09", "2024-01-10"]),
            ),
        )

        rates = get_tbill_rates(date(2024, 1, 1), date(2024, 1, 10))

        assert [d for d, _ in rates] == [date(2024, 1, 8), date(2024, 1, 10)]

    @patch("dm.data.Fred")
    @patch("dm.data.load_dotenv")
    @patch("dm.data.os.getenv")
    def test_raises_when_api_key_missing(
        self, mock_getenv, _mock_load_dotenv, mock_fred_class
    ):
        mock_getenv.return_value = None

        with pytest.raises(ValueError, match="FRED_API_KEY"):
            get_tbill_rates(date(2024, 1, 1), date(2024, 1, 10))

        mock_fred_class.assert_not_called()

    @patch("dm.data.Fred")
    @patch("dm.data.load_dotenv")
    @patch("dm.data.os.getenv")
    def test_raises_on_empty_series(
        self, mock_getenv, _mock_load_dotenv, mock_fred_class
    ):
        mock_getenv.return_value = "fake_api_key"
        self._patched_fred(mock_fred_class, pd.Series(dtype=float))

        with pytest.raises(ValueError, match="No T-bill rate data"):
            get_tbill_rates(date(2024, 1, 1), date(2024, 1, 10))

    @patch("dm.data.Fred")
    @patch("dm.data.load_dotenv")
    @patch("dm.data.os.getenv")
    def test_raises_when_every_observation_is_nan(
        self, mock_getenv, _mock_load_dotenv, mock_fred_class
    ):
        mock_getenv.return_value = "fake_api_key"
        self._patched_fred(
            mock_fred_class,
            pd.Series(
                [float("nan"), float("nan")],
                index=pd.to_datetime(["2024-01-08", "2024-01-09"]),
            ),
        )

        with pytest.raises(ValueError, match="No T-bill rate data"):
            get_tbill_rates(date(2024, 1, 1), date(2024, 1, 10))


def _td_response(values: list[dict] | None = None, body: dict | None = None) -> Mock:
    """Build a mock `requests.Response` for TwelveData."""
    resp = Mock(status_code=200)
    if body is not None:
        resp.json.return_value = body
    else:
        resp.json.return_value = {"meta": {"symbol": "VOO"}, "values": values or []}
    resp.raise_for_status = Mock()
    return resp


class TestGetPriceHistoryTwelveData:
    """Tests for `_get_price_history_twelvedata` — the wide-window TwelveData fetcher."""

    @patch("dm.data.requests.get")
    @patch("dm.data.os.getenv")
    def test_returns_list_of_bars(self, mock_getenv, mock_get):
        mock_getenv.return_value = "fake_key"
        mock_get.return_value = _td_response(
            values=[
                {"datetime": "2024-01-10", "close": "102.00"},
                {"datetime": "2024-01-09", "close": "101.00"},
                {"datetime": "2024-01-08", "close": "100.00"},
            ],
        )

        bars = _get_price_history_twelvedata("VOO", date(2024, 1, 1), date(2024, 1, 10))

        assert sorted(bars) == [
            (date(2024, 1, 8), 100.0),
            (date(2024, 1, 9), 101.0),
            (date(2024, 1, 10), 102.0),
        ]

    @patch("dm.data.requests.get")
    @patch("dm.data.os.getenv")
    def test_sends_start_and_end_date_params(self, mock_getenv, mock_get):
        mock_getenv.return_value = "fake_key"
        mock_get.return_value = _td_response(
            values=[{"datetime": "2024-06-10", "close": "500.00"}],
        )

        _get_price_history_twelvedata("VOO", date(2024, 1, 10), date(2024, 6, 10))

        args, kwargs = mock_get.call_args
        assert args[0] == "https://api.twelvedata.com/time_series"
        params = kwargs["params"]
        assert params["symbol"] == "VOO"
        assert params["interval"] == "1day"
        assert params["apikey"] == "fake_key"
        assert params["start_date"] == "2024-01-10"
        # TwelveData's end_date is exclusive; ask for the day after so the
        # caller's end date is included.
        assert params["end_date"] == "2024-06-11"

    @patch("dm.data.requests.get")
    @patch("dm.data.os.getenv")
    def test_drops_bars_after_the_end_date(self, mock_getenv, mock_get):
        mock_getenv.return_value = "fake_key"
        mock_get.return_value = _td_response(
            values=[
                {"datetime": "2024-06-11", "close": "999.00"},
                {"datetime": "2024-06-10", "close": "500.00"},
            ],
        )

        bars = _get_price_history_twelvedata(
            "VOO", date(2024, 1, 10), date(2024, 6, 10)
        )

        assert bars == [(date(2024, 6, 10), 500.0)]

    @patch("dm.data.requests.get")
    @patch("dm.data.os.getenv")
    def test_requests_dividend_adjusted_closes(self, mock_getenv, mock_get):
        """Momentum needs total return: TwelveData must adjust for dividends.

        TwelveData defaults to `adjust=splits`, which leaves dividends out and
        understates 6-month returns by tens of basis points.
        """
        mock_getenv.return_value = "fake_key"
        mock_get.return_value = _td_response(
            values=[{"datetime": "2024-06-10", "close": "500.00"}],
        )

        _get_price_history_twelvedata("VXUS", date(2024, 1, 10), date(2024, 6, 10))

        assert mock_get.call_args.kwargs["params"]["adjust"] == "all"

    @patch("dm.data.requests.get")
    @patch("dm.data.os.getenv")
    def test_parses_iso_datetime_with_time_component(self, mock_getenv, mock_get):
        mock_getenv.return_value = "fake_key"
        mock_get.return_value = _td_response(
            values=[{"datetime": "2024-01-10T00:00:00Z", "close": "99.50"}],
        )

        bars = _get_price_history_twelvedata("VOO", date(2024, 1, 1), date(2024, 1, 10))

        assert bars == [(date(2024, 1, 10), 99.5)]

    @patch("dm.data.requests.get")
    @patch("dm.data.os.getenv")
    def test_raises_when_api_key_missing(self, mock_getenv, mock_get):
        mock_getenv.return_value = None

        with pytest.raises(ValueError, match="TWELVEDATA_API_KEY"):
            _get_price_history_twelvedata("VOO", date(2024, 1, 1), date(2024, 1, 10))

        mock_get.assert_not_called()

    @patch("dm.data.requests.get")
    @patch("dm.data.os.getenv")
    def test_raises_on_empty_values(self, mock_getenv, mock_get):
        mock_getenv.return_value = "fake_key"
        mock_get.return_value = _td_response(values=[])

        with pytest.raises(ValueError, match="No price data"):
            _get_price_history_twelvedata("VOO", date(2024, 1, 1), date(2024, 1, 10))

    @patch("dm.data.requests.get")
    @patch("dm.data.os.getenv")
    def test_raises_on_api_error_body(self, mock_getenv, mock_get):
        mock_getenv.return_value = "fake_key"
        mock_get.return_value = _td_response(
            body={"code": 429, "message": "Rate limit", "status": "error"},
        )

        with pytest.raises(RuntimeError, match="Rate limit"):
            _get_price_history_twelvedata("VOO", date(2024, 1, 1), date(2024, 1, 10))

    @patch("dm.data.requests.get")
    @patch("dm.data.os.getenv")
    def test_raises_on_http_error(self, mock_getenv, mock_get):
        mock_getenv.return_value = "fake_key"
        resp = Mock(status_code=500)
        resp.raise_for_status.side_effect = requests.HTTPError("500 Server Error")
        mock_get.return_value = resp

        with pytest.raises(requests.HTTPError):
            _get_price_history_twelvedata("VOO", date(2024, 1, 1), date(2024, 1, 10))


class TestGetPriceHistoryYFinance:
    """Tests for `_get_price_history_yfinance` — the wide-window yfinance fetcher."""

    @patch("dm.data.yf.Ticker")
    def test_returns_list_of_bars(self, mock_ticker_class):
        mock_ticker = Mock()
        mock_ticker_class.return_value = mock_ticker
        mock_ticker.history.return_value = pd.DataFrame(
            {"Close": [100.0, 101.0, 102.0]},
            index=pd.to_datetime(["2024-01-08", "2024-01-09", "2024-01-10"]),
        )

        bars = _get_price_history_yfinance("VOO", date(2024, 1, 1), date(2024, 1, 10))

        assert bars == [
            (date(2024, 1, 8), 100.0),
            (date(2024, 1, 9), 101.0),
            (date(2024, 1, 10), 102.0),
        ]
        mock_ticker_class.assert_called_once_with("VOO")

    @patch("dm.data.yf.Ticker")
    def test_passes_inclusive_end_date_to_yfinance(self, mock_ticker_class):
        """yfinance.history treats `end` as exclusive — the fetcher must add a day."""
        mock_ticker = Mock()
        mock_ticker_class.return_value = mock_ticker
        mock_ticker.history.return_value = pd.DataFrame(
            {"Close": [100.0]}, index=pd.to_datetime(["2024-01-10"])
        )

        _get_price_history_yfinance("VOO", date(2024, 1, 1), date(2024, 1, 10))

        args, kwargs = mock_ticker.history.call_args
        assert kwargs["start"] == date(2024, 1, 1)
        assert kwargs["end"] == date(2024, 1, 11)  # exclusive, so +1 day

    @patch("dm.data.yf.Ticker")
    def test_requests_dividend_adjusted_closes(self, mock_ticker_class):
        """Momentum needs total return, so auto_adjust must be explicit."""
        mock_ticker = Mock()
        mock_ticker_class.return_value = mock_ticker
        mock_ticker.history.return_value = pd.DataFrame(
            {"Close": [100.0]}, index=pd.to_datetime(["2024-01-10"])
        )

        _get_price_history_yfinance("VOO", date(2024, 1, 1), date(2024, 1, 10))

        assert mock_ticker.history.call_args.kwargs["auto_adjust"] is True

    @patch("dm.data.yf.Ticker")
    def test_raises_on_empty_history(self, mock_ticker_class):
        mock_ticker = Mock()
        mock_ticker_class.return_value = mock_ticker
        mock_ticker.history.return_value = pd.DataFrame(
            {"Close": []}, index=pd.to_datetime([])
        )

        with pytest.raises(ValueError, match="No price data"):
            _get_price_history_yfinance("VOO", date(2024, 1, 1), date(2024, 1, 10))


class TestGetPriceHistoryFallback:
    """Tests for `get_price_history` — TwelveData-first with yfinance fallback."""

    @patch("dm.data._get_price_history_yfinance")
    @patch("dm.data._get_price_history_twelvedata")
    def test_uses_twelvedata_when_successful(self, mock_td, mock_yf, recwarn):
        bars = [(date(2024, 1, 10), 102.0)]
        mock_td.return_value = bars

        result = get_price_history("VOO", date(2024, 1, 1), date(2024, 1, 10))

        assert result == bars
        mock_td.assert_called_once_with("VOO", date(2024, 1, 1), date(2024, 1, 10))
        mock_yf.assert_not_called()
        assert [w for w in recwarn.list if issubclass(w.category, UserWarning)] == []

    @patch("dm.data._get_price_history_yfinance")
    @patch("dm.data._get_price_history_twelvedata")
    def test_falls_back_on_twelvedata_error(self, mock_td, mock_yf):
        mock_td.side_effect = RuntimeError("Rate limit")
        mock_yf.return_value = [(date(2024, 1, 10), 99.0)]

        with pytest.warns(UserWarning, match="yfinance fallback"):
            result = get_price_history("VOO", date(2024, 1, 1), date(2024, 1, 10))

        assert result == [(date(2024, 1, 10), 99.0)]
        mock_yf.assert_called_once_with("VOO", date(2024, 1, 1), date(2024, 1, 10))

    @patch("dm.data._get_price_history_yfinance")
    @patch("dm.data._get_price_history_twelvedata")
    def test_raises_when_both_fail(self, mock_td, mock_yf):
        mock_td.side_effect = RuntimeError("TD down")
        mock_yf.side_effect = ValueError("yfinance empty")

        with pytest.warns(UserWarning, match="yfinance fallback"):
            with pytest.raises(ValueError, match="yfinance empty"):
                get_price_history("VOO", date(2024, 1, 1), date(2024, 1, 10))

    @patch("dm.data._get_price_history_yfinance")
    @patch("dm.data._get_price_history_twelvedata")
    def test_warning_fires_only_once_per_process(self, mock_td, mock_yf, recwarn):
        """One warning per run, however many symbols fall back."""
        mock_td.side_effect = RuntimeError("down")
        mock_yf.return_value = [(date(2024, 1, 10), 99.0)]

        for symbol in ["VOO", "VXUS", "VGIT"]:
            get_price_history(symbol, date(2024, 1, 1), date(2024, 1, 10))

        fallback_warnings = [
            w for w in recwarn.list if issubclass(w.category, UserWarning)
        ]
        assert len(fallback_warnings) == 1
        assert mock_yf.call_count == 3

"""Tests for data fetching."""

from datetime import date, timedelta
from unittest.mock import Mock, patch

import pandas as pd
import pytest
import requests

from dm.data import (
    _get_price_twelvedata,
    _get_price_yfinance,
    get_price,
    get_treasury_rate,
)


class TestGetPriceYFinance:
    """Tests for `_get_price_yfinance` — the yfinance fallback fetcher."""

    @patch("dm.data.yf.Ticker")
    def test_get_price_for_date(self, mock_ticker_class):
        """Test fetching price for a specific date."""
        mock_ticker = Mock()
        mock_ticker_class.return_value = mock_ticker

        # Create mock history data
        mock_history = pd.DataFrame(
            {"Close": [100.0, 101.0, 102.0]},
            index=pd.to_datetime(["2024-01-08", "2024-01-09", "2024-01-10"]),
        )
        mock_ticker.history.return_value = mock_history

        result = _get_price_yfinance("VOO", date(2024, 1, 10))

        assert result == 102.0
        mock_ticker_class.assert_called_once_with("VOO")

    @patch("dm.data.yf.Ticker")
    def test_get_price_uses_most_recent_if_date_missing(self, mock_ticker_class):
        """Test that most recent price is used if exact date not available."""
        mock_ticker = Mock()
        mock_ticker_class.return_value = mock_ticker

        # Data doesn't include the target date (weekend)
        mock_history = pd.DataFrame(
            {"Close": [100.0, 101.0]},
            index=pd.to_datetime(["2024-01-11", "2024-01-12"]),
        )
        mock_ticker.history.return_value = mock_history

        # Request Saturday's price - should get Friday's
        result = _get_price_yfinance("VOO", date(2024, 1, 13))

        assert result == 101.0

    @patch("dm.data.yf.Ticker")
    def test_get_price_vxus(self, mock_ticker_class):
        """Test fetching VXUS price."""
        mock_ticker = Mock()
        mock_ticker_class.return_value = mock_ticker

        mock_history = pd.DataFrame(
            {"Close": [55.0]},
            index=pd.to_datetime(["2024-01-10"]),
        )
        mock_ticker.history.return_value = mock_history

        result = _get_price_yfinance("VXUS", date(2024, 1, 10))

        assert result == 55.0
        mock_ticker_class.assert_called_once_with("VXUS")


class TestGetTreasuryRate:
    """Tests for fetching treasury rates from FRED."""

    @patch("dm.data.Fred")
    @patch("dm.data.load_dotenv")
    @patch("dm.data.os.getenv")
    def test_get_treasury_rate(self, mock_getenv, mock_load_dotenv, mock_fred_class):
        """Test fetching treasury rate."""
        mock_getenv.return_value = "fake_api_key"
        mock_fred = Mock()
        mock_fred_class.return_value = mock_fred

        # FRED returns rates as percentages (e.g., 5.0 for 5%)
        mock_series = pd.Series(
            [4.5, 4.6, 4.7],
            index=pd.to_datetime(["2024-01-08", "2024-01-09", "2024-01-10"]),
        )
        mock_fred.get_series.return_value = mock_series

        result = get_treasury_rate(date(2024, 1, 10))

        # Should return as decimal (4.7% -> 0.047)
        assert result == pytest.approx(0.047)
        mock_fred.get_series.assert_called_once()

    @patch("dm.data.Fred")
    @patch("dm.data.load_dotenv")
    @patch("dm.data.os.getenv")
    def test_get_treasury_rate_uses_most_recent(
        self, mock_getenv, mock_load_dotenv, mock_fred_class
    ):
        """Test that most recent rate is used if exact date not available."""
        mock_getenv.return_value = "fake_api_key"
        mock_fred = Mock()
        mock_fred_class.return_value = mock_fred

        mock_series = pd.Series(
            [4.5, 4.6],
            index=pd.to_datetime(["2024-01-11", "2024-01-12"]),
        )
        mock_fred.get_series.return_value = mock_series

        # Request date after last available
        result = get_treasury_rate(date(2024, 1, 15))

        assert result == pytest.approx(0.046)


def _td_response(values: list[dict] | None = None, body: dict | None = None) -> Mock:
    """Build a mock `requests.Response` for TwelveData."""
    resp = Mock(status_code=200)
    if body is not None:
        resp.json.return_value = body
    else:
        resp.json.return_value = {"meta": {"symbol": "VOO"}, "values": values or []}
    resp.raise_for_status = Mock()
    return resp


class TestGetPriceTwelveData:
    """Tests for `_get_price_twelvedata` — the TwelveData REST fetcher."""

    @patch("dm.data.requests.get")
    @patch("dm.data.os.getenv")
    def test_returns_close_for_target_date(self, mock_getenv, mock_get):
        mock_getenv.return_value = "fake_key"
        mock_get.return_value = _td_response(
            values=[
                {"datetime": "2024-01-10", "close": "102.00"},
                {"datetime": "2024-01-09", "close": "101.00"},
                {"datetime": "2024-01-08", "close": "100.00"},
            ],
        )

        result = _get_price_twelvedata("VOO", date(2024, 1, 10))

        assert result == 102.0

    @patch("dm.data.requests.get")
    @patch("dm.data.os.getenv")
    def test_uses_most_recent_on_or_before(self, mock_getenv, mock_get):
        mock_getenv.return_value = "fake_key"
        # Data ends Friday; request Sunday.
        mock_get.return_value = _td_response(
            values=[
                {"datetime": "2024-01-12", "close": "101.00"},
                {"datetime": "2024-01-11", "close": "100.00"},
            ],
        )

        result = _get_price_twelvedata("VOO", date(2024, 1, 14))

        assert result == 101.0

    @patch("dm.data.requests.get")
    @patch("dm.data.os.getenv")
    def test_parses_iso_datetime_with_time_component(self, mock_getenv, mock_get):
        mock_getenv.return_value = "fake_key"
        mock_get.return_value = _td_response(
            values=[{"datetime": "2024-01-10T00:00:00Z", "close": "99.50"}],
        )

        result = _get_price_twelvedata("VOO", date(2024, 1, 10))

        assert result == 99.5

    @patch("dm.data.requests.get")
    @patch("dm.data.os.getenv")
    def test_raises_when_api_key_missing(self, mock_getenv, mock_get):
        mock_getenv.return_value = None

        with pytest.raises(ValueError, match="TWELVEDATA_API_KEY"):
            _get_price_twelvedata("VOO", date(2024, 1, 10))

        mock_get.assert_not_called()

    @patch("dm.data.requests.get")
    @patch("dm.data.os.getenv")
    def test_raises_on_empty_values(self, mock_getenv, mock_get):
        mock_getenv.return_value = "fake_key"
        mock_get.return_value = _td_response(values=[])

        with pytest.raises(ValueError, match="No price data"):
            _get_price_twelvedata("VOO", date(2024, 1, 10))

    @patch("dm.data.requests.get")
    @patch("dm.data.os.getenv")
    def test_raises_when_no_value_on_or_before_target(self, mock_getenv, mock_get):
        mock_getenv.return_value = "fake_key"
        # All values are AFTER the target date
        mock_get.return_value = _td_response(
            values=[{"datetime": "2024-01-15", "close": "103.00"}],
        )

        with pytest.raises(ValueError, match="on or before"):
            _get_price_twelvedata("VOO", date(2024, 1, 10))

    @patch("dm.data.requests.get")
    @patch("dm.data.os.getenv")
    def test_raises_on_api_error_body(self, mock_getenv, mock_get):
        mock_getenv.return_value = "fake_key"
        mock_get.return_value = _td_response(
            body={"code": 429, "message": "Rate limit", "status": "error"},
        )

        with pytest.raises(RuntimeError, match="Rate limit"):
            _get_price_twelvedata("VOO", date(2024, 1, 10))

    @patch("dm.data.requests.get")
    @patch("dm.data.os.getenv")
    def test_raises_on_http_error(self, mock_getenv, mock_get):
        mock_getenv.return_value = "fake_key"
        resp = Mock(status_code=500)
        resp.raise_for_status.side_effect = requests.HTTPError("500 Server Error")
        mock_get.return_value = resp

        with pytest.raises(requests.HTTPError):
            _get_price_twelvedata("VOO", date(2024, 1, 10))

    @patch("dm.data.requests.get")
    @patch("dm.data.os.getenv")
    def test_sends_expected_request_params(self, mock_getenv, mock_get):
        mock_getenv.return_value = "fake_key"
        mock_get.return_value = _td_response(
            values=[{"datetime": "2024-01-10", "close": "100.00"}],
        )

        _get_price_twelvedata("VOO", date(2024, 1, 10))

        args, kwargs = mock_get.call_args
        assert args[0] == "https://api.twelvedata.com/time_series"
        params = kwargs["params"]
        assert params["symbol"] == "VOO"
        assert params["interval"] == "1day"
        assert params["apikey"] == "fake_key"
        assert params["end_date"] == "2024-01-10"
        # start_date should be ~10 days earlier to cover weekends/holidays
        expected_start = (date(2024, 1, 10) - timedelta(days=10)).isoformat()
        assert params["start_date"] == expected_start


class TestGetPriceFallback:
    """Tests for the `get_price` orchestrator: TwelveData-first with yfinance fallback."""

    @patch("dm.data._get_price_yfinance")
    @patch("dm.data._get_price_twelvedata")
    def test_uses_twelvedata_when_successful(self, mock_td, mock_yf, recwarn):
        mock_td.return_value = 102.0

        result = get_price("VOO", date(2024, 1, 10))

        assert result == 102.0
        mock_td.assert_called_once_with("VOO", date(2024, 1, 10))
        mock_yf.assert_not_called()
        # No warnings on the happy path
        assert [w for w in recwarn.list if issubclass(w.category, UserWarning)] == []

    @patch("dm.data._get_price_yfinance")
    @patch("dm.data._get_price_twelvedata")
    def test_falls_back_to_yfinance_on_twelvedata_error(self, mock_td, mock_yf):
        mock_td.side_effect = RuntimeError("TwelveData API error: Rate limit")
        mock_yf.return_value = 99.9

        with pytest.warns(UserWarning, match="yfinance fallback"):
            result = get_price("VOO", date(2024, 1, 10))

        assert result == 99.9
        mock_yf.assert_called_once_with("VOO", date(2024, 1, 10))

    @patch("dm.data._get_price_yfinance")
    @patch("dm.data._get_price_twelvedata")
    def test_falls_back_when_api_key_missing(self, mock_td, mock_yf):
        mock_td.side_effect = ValueError("TWELVEDATA_API_KEY not found in environment")
        mock_yf.return_value = 50.0

        with pytest.warns(UserWarning, match="yfinance fallback"):
            result = get_price("VOO", date(2024, 1, 10))

        assert result == 50.0
        mock_yf.assert_called_once_with("VOO", date(2024, 1, 10))

    @patch("dm.data._get_price_yfinance")
    @patch("dm.data._get_price_twelvedata")
    def test_falls_back_on_network_error(self, mock_td, mock_yf):
        mock_td.side_effect = requests.ConnectionError("network unreachable")
        mock_yf.return_value = 77.0

        with pytest.warns(UserWarning, match="yfinance fallback"):
            result = get_price("VOO", date(2024, 1, 10))

        assert result == 77.0

    @patch("dm.data._get_price_yfinance")
    @patch("dm.data._get_price_twelvedata")
    def test_raises_when_both_sources_fail(self, mock_td, mock_yf):
        mock_td.side_effect = RuntimeError("TD down")
        mock_yf.side_effect = ValueError("yfinance empty")

        with pytest.warns(UserWarning, match="yfinance fallback"):
            with pytest.raises(ValueError, match="yfinance empty"):
                get_price("VOO", date(2024, 1, 10))

    @patch("dm.data._get_price_yfinance")
    @patch("dm.data._get_price_twelvedata")
    def test_warning_fires_only_once_across_calls(self, mock_td, mock_yf, recwarn):
        mock_td.side_effect = RuntimeError("TD down")
        mock_yf.return_value = 10.0

        for _ in range(5):
            get_price("VOO", date(2024, 1, 10))

        fallback_warnings = [
            w for w in recwarn.list if issubclass(w.category, UserWarning)
        ]
        assert len(fallback_warnings) == 1
        assert mock_yf.call_count == 5

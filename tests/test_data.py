"""Tests for data fetching."""

from datetime import date, timedelta
from unittest.mock import Mock, patch

import pandas as pd
import pytest

from dm.data import get_price, get_treasury_rate


class TestGetPrice:
    """Tests for fetching security prices."""

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

        result = get_price("VOO", date(2024, 1, 10))

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
        result = get_price("VOO", date(2024, 1, 13))

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

        result = get_price("VXUS", date(2024, 1, 10))

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

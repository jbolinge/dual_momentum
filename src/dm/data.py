"""Data fetching from TwelveData (primary), yfinance (fallback), and FRED."""

import os
import warnings
from datetime import date, timedelta

import requests
import yfinance as yf
from dotenv import load_dotenv
from fredapi import Fred

_TWELVEDATA_URL = "https://api.twelvedata.com/time_series"
_PRICE_WINDOW_DAYS = 10
_REQUEST_TIMEOUT_SECONDS = 10


def _select_latest_on_or_before(
    bars: list[tuple[date, float]], target_date: date, symbol: str
) -> float:
    """Return the close price for the most recent bar dated on or before target."""
    if not bars:
        raise ValueError(f"No price data found for {symbol}")
    valid = [(d, p) for d, p in bars if d <= target_date]
    if not valid:
        raise ValueError(f"No price data found for {symbol} on or before {target_date}")
    valid.sort(key=lambda x: x[0])
    return valid[-1][1]


def _get_price_twelvedata(symbol: str, target_date: date) -> float:
    """Fetch closing price from TwelveData for `symbol` on or before `target_date`.

    Raises:
        ValueError: if TWELVEDATA_API_KEY is unset or no usable data is returned.
        RuntimeError: if the API returns a JSON error body.
        requests.RequestException: on network or HTTP errors.
    """
    load_dotenv()
    api_key = os.getenv("TWELVEDATA_API_KEY")
    if not api_key:
        raise ValueError("TWELVEDATA_API_KEY not found in environment")

    start_date = (target_date - timedelta(days=_PRICE_WINDOW_DAYS)).isoformat()
    end_date = target_date.isoformat()

    response = requests.get(
        _TWELVEDATA_URL,
        params={
            "symbol": symbol,
            "interval": "1day",
            "start_date": start_date,
            "end_date": end_date,
            "apikey": api_key,
        },
        timeout=_REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    payload = response.json()

    if payload.get("status") == "error":
        raise RuntimeError(
            f"TwelveData API error: {payload.get('message', 'unknown error')}"
        )

    bars = [
        (date.fromisoformat(v["datetime"][:10]), float(v["close"]))
        for v in payload.get("values", [])
    ]
    return _select_latest_on_or_before(bars, target_date, symbol)


def _get_price_yfinance(symbol: str, target_date: date) -> float:
    """Fetch closing price from yfinance for `symbol` on or before `target_date`."""
    ticker = yf.Ticker(symbol)

    # yfinance `end` is exclusive; add a day so target_date is included.
    start_date = target_date - timedelta(days=_PRICE_WINDOW_DAYS)
    end_date = target_date + timedelta(days=1)
    history = ticker.history(start=start_date, end=end_date)

    if history.empty:
        raise ValueError(f"No price data found for {symbol}")

    history.index = history.index.tz_localize(None)
    bars = [
        (ts.date(), float(close)) for ts, close in zip(history.index, history["Close"])
    ]
    return _select_latest_on_or_before(bars, target_date, symbol)


def get_price(symbol: str, target_date: date) -> float:
    """Fetch closing price for a security on or before target date.

    Tries TwelveData first; on any failure, warns and falls back to yfinance.

    Args:
        symbol: Stock ticker symbol (e.g., 'VOO', 'VXUS')
        target_date: Date to fetch price for

    Returns:
        Closing price. If no data for exact date, returns most recent prior.
    """
    try:
        return _get_price_twelvedata(symbol, target_date)
    except Exception as twelvedata_error:
        warnings.warn(
            f"TwelveData unavailable ({twelvedata_error}); using yfinance fallback",
            UserWarning,
            stacklevel=2,
        )
        return _get_price_yfinance(symbol, target_date)


def get_treasury_rate(target_date: date) -> float:
    """Fetch 1-month treasury rate from FRED on or before target date.

    Args:
        target_date: Date to fetch rate for

    Returns:
        Annualized rate as decimal (e.g., 0.05 for 5%).
        If no data for exact date, returns most recent prior.
    """
    load_dotenv()
    api_key = os.getenv("FRED_API_KEY")

    if not api_key:
        raise ValueError("FRED_API_KEY not found in environment")

    fred = Fred(api_key=api_key)

    # Fetch DGS1MO series (1-Month Treasury Constant Maturity Rate)
    start_date = target_date - timedelta(days=30)
    series = fred.get_series("DGS1MO", start_date, target_date)

    if series.empty:
        raise ValueError(f"No treasury rate data found for {target_date}")

    # Get most recent rate on or before target date
    valid_rates = series[series.index.date <= target_date]

    if valid_rates.empty:
        raise ValueError(f"No treasury rate data found on or before {target_date}")

    # FRED returns rate as percentage (e.g., 5.0), convert to decimal
    return float(valid_rates.iloc[-1]) / 100

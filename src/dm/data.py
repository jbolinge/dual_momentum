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


class TwelveDataFallbackWarning(UserWarning):
    """Emitted when a price lookup falls back from TwelveData to yfinance."""


# Module-level latch: once a fallback warning has fired this process, stay silent.
_fallback_warned = False


def _reset_fallback_warning() -> None:
    """Reset the fallback-warning latch (for tests)."""
    global _fallback_warned
    _fallback_warned = False


def select_price_on_or_before(
    bars: list[tuple[date, float]], target_date: date, symbol: str
) -> float:
    """Return the close price for the most recent bar dated on or before target.

    Use this to pick a single price out of a wide history window, e.g. the
    result of `get_price_history`. The `symbol` argument is only used to
    build the error message when no usable bar exists.
    """
    if not bars:
        raise ValueError(f"No price data found for {symbol}")
    valid = [(d, p) for d, p in bars if d <= target_date]
    if not valid:
        raise ValueError(f"No price data found for {symbol} on or before {target_date}")
    valid.sort(key=lambda x: x[0])
    return valid[-1][1]


def _get_price_history_twelvedata(
    symbol: str, start_date: date, end_date: date
) -> list[tuple[date, float]]:
    """Fetch daily close bars from TwelveData for `symbol` in [start_date, end_date].

    Raises:
        ValueError: if TWELVEDATA_API_KEY is unset or the response has no bars.
        RuntimeError: if the API returns a JSON error body.
        requests.RequestException: on network or HTTP errors.
    """
    load_dotenv()
    api_key = os.getenv("TWELVEDATA_API_KEY")
    if not api_key:
        raise ValueError("TWELVEDATA_API_KEY not found in environment")

    response = requests.get(
        _TWELVEDATA_URL,
        params={
            "symbol": symbol,
            "interval": "1day",
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
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

    values = payload.get("values", [])
    if not values:
        raise ValueError(f"No price data found for {symbol}")

    return [(date.fromisoformat(v["datetime"][:10]), float(v["close"])) for v in values]


def _get_price_twelvedata(symbol: str, target_date: date) -> float:
    """Fetch closing price from TwelveData for `symbol` on or before `target_date`."""
    start_date = target_date - timedelta(days=_PRICE_WINDOW_DAYS)
    bars = _get_price_history_twelvedata(symbol, start_date, target_date)
    return select_price_on_or_before(bars, target_date, symbol)


def _get_price_history_yfinance(
    symbol: str, start_date: date, end_date: date
) -> list[tuple[date, float]]:
    """Fetch daily close bars from yfinance for `symbol` in [start_date, end_date].

    The end_date is inclusive from the caller's perspective — yfinance's
    `history()` treats `end` as exclusive, so we add one day internally.
    """
    ticker = yf.Ticker(symbol)
    history = ticker.history(start=start_date, end=end_date + timedelta(days=1))

    if history.empty:
        raise ValueError(f"No price data found for {symbol}")

    history.index = history.index.tz_localize(None)
    return [
        (ts.date(), float(close)) for ts, close in zip(history.index, history["Close"])
    ]


def _get_price_yfinance(symbol: str, target_date: date) -> float:
    """Fetch closing price from yfinance for `symbol` on or before `target_date`."""
    start_date = target_date - timedelta(days=_PRICE_WINDOW_DAYS)
    bars = _get_price_history_yfinance(symbol, start_date, target_date)
    return select_price_on_or_before(bars, target_date, symbol)


def _call_with_fallback(primary, fallback):
    """Run `primary()`; on any exception, warn once per process and run `fallback()`."""
    global _fallback_warned
    try:
        return primary()
    except Exception as twelvedata_error:
        if not _fallback_warned:
            warnings.warn(
                f"TwelveData unavailable ({twelvedata_error}); using yfinance fallback",
                TwelveDataFallbackWarning,
                stacklevel=3,
            )
            _fallback_warned = True
        return fallback()


def get_price(symbol: str, target_date: date) -> float:
    """Fetch closing price for a security on or before target date.

    Tries TwelveData first; on any failure, warns and falls back to yfinance.

    Args:
        symbol: Stock ticker symbol (e.g., 'VOO', 'VXUS')
        target_date: Date to fetch price for

    Returns:
        Closing price. If no data for exact date, returns most recent prior.
    """
    return _call_with_fallback(
        lambda: _get_price_twelvedata(symbol, target_date),
        lambda: _get_price_yfinance(symbol, target_date),
    )


def get_price_history(
    symbol: str, start_date: date, end_date: date
) -> list[tuple[date, float]]:
    """Fetch daily close bars for a symbol in [start_date, end_date].

    Tries TwelveData first; on any failure, warns and falls back to yfinance.
    Use `select_price_on_or_before` to pick a single target date out of the
    returned list — one wide-window fetch serves many target-date lookups.
    """
    return _call_with_fallback(
        lambda: _get_price_history_twelvedata(symbol, start_date, end_date),
        lambda: _get_price_history_yfinance(symbol, start_date, end_date),
    )


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

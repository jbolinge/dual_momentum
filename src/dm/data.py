"""Data fetching from TwelveData (primary), yfinance (fallback), and FRED."""

import os
import warnings
from datetime import date, timedelta

import requests
import yfinance as yf
from dotenv import load_dotenv
from fredapi import Fred

_TWELVEDATA_URL = "https://api.twelvedata.com/time_series"
_REQUEST_TIMEOUT_SECONDS = 10


class TwelveDataFallbackWarning(UserWarning):
    """Emitted when a price lookup falls back from TwelveData to yfinance."""


# Module-level latch: once a fallback warning has fired this process, stay silent.
_fallback_warned = False


def _reset_fallback_warning() -> None:
    """Reset the fallback-warning latch (for tests)."""
    global _fallback_warned
    _fallback_warned = False


def _get_price_history_twelvedata(
    symbol: str, start_date: date, end_date: date
) -> list[tuple[date, float]]:
    """Fetch daily close bars from TwelveData for `symbol` in [start_date, end_date].

    Closes are dividend- and split-adjusted (`adjust=all`), i.e. total return.
    TwelveData's default is `adjust=splits`, which drops dividends and
    understates momentum lookbacks.

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
            "adjust": "all",
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


def _get_price_history_yfinance(
    symbol: str, start_date: date, end_date: date
) -> list[tuple[date, float]]:
    """Fetch daily close bars from yfinance for `symbol` in [start_date, end_date].

    Closes are dividend- and split-adjusted (`auto_adjust=True`), i.e. total
    return, matching the TwelveData `adjust=all` primary path.

    The end_date is inclusive from the caller's perspective — yfinance's
    `history()` treats `end` as exclusive, so we add one day internally.
    """
    ticker = yf.Ticker(symbol)
    history = ticker.history(
        start=start_date, end=end_date + timedelta(days=1), auto_adjust=True
    )

    if history.empty:
        raise ValueError(f"No price data found for {symbol}")

    history.index = history.index.tz_localize(None)
    return [
        (ts.date(), float(close)) for ts, close in zip(history.index, history["Close"])
    ]


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


def get_price_history(
    symbol: str, start_date: date, end_date: date
) -> list[tuple[date, float]]:
    """Fetch daily close bars for a symbol in [start_date, end_date].

    Both sources return dividend- and split-adjusted (total return) closes.
    Tries TwelveData first; on any failure, warns and falls back to yfinance.
    """
    return _call_with_fallback(
        lambda: _get_price_history_twelvedata(symbol, start_date, end_date),
        lambda: _get_price_history_yfinance(symbol, start_date, end_date),
    )


def get_tbill_rates(start_date: date, end_date: date) -> list[tuple[date, float]]:
    """Fetch the 3-month Treasury bill rate from FRED for [start_date, end_date].

    Series DTB3 (3-Month Treasury Bill Secondary Market Rate, daily) is the
    risk-free benchmark for absolute momentum. Holidays come back as NaN and
    are dropped.

    Returns:
        Ascending (date, annualized rate as decimal) pairs, e.g. 0.0525 for 5.25%.
    """
    load_dotenv()
    api_key = os.getenv("FRED_API_KEY")

    if not api_key:
        raise ValueError("FRED_API_KEY not found in environment")

    fred = Fred(api_key=api_key)
    series = fred.get_series("DTB3", start_date, end_date).dropna()

    if series.empty:
        raise ValueError(
            f"No T-bill rate data found between {start_date} and {end_date}"
        )

    # FRED returns rates as percentages (e.g., 5.25), convert to decimals.
    return [(timestamp.date(), float(rate) / 100) for timestamp, rate in series.items()]

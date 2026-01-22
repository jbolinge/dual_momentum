"""Data fetching from yfinance and FRED."""

import os
from datetime import date, timedelta

import yfinance as yf
from dotenv import load_dotenv
from fredapi import Fred


def get_price(symbol: str, target_date: date) -> float:
    """Fetch closing price for a security on or before target date.

    Args:
        symbol: Stock ticker symbol (e.g., 'VOO', 'VXUS')
        target_date: Date to fetch price for

    Returns:
        Closing price. If no data for exact date, returns most recent prior.
    """
    ticker = yf.Ticker(symbol)

    # Fetch extra days to ensure we have data before target date
    start_date = target_date - timedelta(days=10)
    end_date = target_date + timedelta(days=1)

    history = ticker.history(start=start_date, end=end_date)

    if history.empty:
        raise ValueError(f"No price data found for {symbol}")

    # Filter to dates on or before target, get most recent
    history.index = history.index.tz_localize(None)
    valid_dates = history[history.index.date <= target_date]

    if valid_dates.empty:
        raise ValueError(f"No price data found for {symbol} on or before {target_date}")

    return float(valid_dates["Close"].iloc[-1])


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

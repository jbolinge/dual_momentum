"""CLI entry point."""

import sys
import warnings
from datetime import date
from dateutil.relativedelta import relativedelta

from dm.data import TwelveDataFallbackWarning, get_price, get_treasury_rate
from dm.returns import (
    calculate_simple_return,
    convert_treasury_rate,
    calculate_weighted_return,
)
from dm.compare import determine_winner, InstrumentReturns


def get_returns_for_symbol(symbol: str, today: date) -> tuple[float, float, float]:
    """Calculate returns for a symbol over 1, 3, and 6 month periods.

    Args:
        symbol: Stock ticker symbol
        today: Reference date (typically today)

    Returns:
        Tuple of (1-month return, 3-month return, 6-month return)
    """
    current_price = get_price(symbol, today)

    date_1m = today - relativedelta(months=1)
    date_3m = today - relativedelta(months=3)
    date_6m = today - relativedelta(months=6)

    price_1m = get_price(symbol, date_1m)
    price_3m = get_price(symbol, date_3m)
    price_6m = get_price(symbol, date_6m)

    return_1m = calculate_simple_return(price_1m, current_price)
    return_3m = calculate_simple_return(price_3m, current_price)
    return_6m = calculate_simple_return(price_6m, current_price)

    return return_1m, return_3m, return_6m


def get_treasury_returns(today: date) -> tuple[float, float, float]:
    """Get treasury returns for 1, 3, and 6 month periods.

    Args:
        today: Reference date

    Returns:
        Tuple of (1-month return, 3-month return, 6-month return)
    """
    annual_rate = get_treasury_rate(today)

    return_1m = convert_treasury_rate(annual_rate, 1)
    return_3m = convert_treasury_rate(annual_rate, 3)
    return_6m = convert_treasury_rate(annual_rate, 6)

    return return_1m, return_3m, return_6m


def format_output(
    voo: InstrumentReturns,
    vxus: InstrumentReturns,
    treasury: InstrumentReturns,
    winners: list[InstrumentReturns],
) -> str:
    """Format the output for display.

    Args:
        voo: VOO returns
        vxus: VXUS returns
        treasury: Treasury returns
        winners: List of winning instrument(s)

    Returns:
        Formatted string for output
    """
    lines = []
    lines.append("Dual Momentum Analysis")
    lines.append("=" * 40)
    lines.append("")

    for inst in [voo, vxus, treasury]:
        lines.append(f"{inst.name}:")
        lines.append(f"  1-Month:  {inst.returns_1m * 100:>7.2f}%")
        lines.append(f"  3-Month:  {inst.returns_3m * 100:>7.2f}%")
        lines.append(f"  6-Month:  {inst.returns_6m * 100:>7.2f}%")
        lines.append(f"  Weighted: {inst.weighted_return * 100:>7.2f}%")
        lines.append("")

    lines.append("=" * 40)
    if len(winners) == 1:
        lines.append(f"Signal: {winners[0].name}")
    else:
        winner_names = ", ".join(w.name for w in winners)
        lines.append(f"Signal: {winner_names}")

    return "\n".join(lines)


def _configure_warnings() -> None:
    # Suppress yfinance's internal pandas deprecation warnings
    # See: https://github.com/ranaroussi/yfinance/issues/1837
    warnings.filterwarnings(
        "ignore",
        message=".*utcnow.*deprecated.*",
        module="yfinance.*",
    )

    # Render TwelveData fallback warnings cleanly to stderr (no file/lineno noise).
    # The warning itself is latched in dm.data and fires at most once per run.
    default_showwarning = warnings.showwarning

    def showwarning(message, category, filename, lineno, file=None, line=None):
        if issubclass(category, TwelveDataFallbackWarning):
            print(f"Warning: {message}", file=sys.stderr)
            return
        default_showwarning(message, category, filename, lineno, file, line)

    warnings.showwarning = showwarning


def main():
    """Main entry point for the dm CLI."""
    _configure_warnings()

    today = date.today()

    # Get returns for each instrument
    voo_1m, voo_3m, voo_6m = get_returns_for_symbol("VOO", today)
    vxus_1m, vxus_3m, vxus_6m = get_returns_for_symbol("VXUS", today)
    tsy_1m, tsy_3m, tsy_6m = get_treasury_returns(today)

    # Calculate weighted returns
    voo_weighted = calculate_weighted_return([voo_1m, voo_3m, voo_6m])
    vxus_weighted = calculate_weighted_return([vxus_1m, vxus_3m, vxus_6m])
    tsy_weighted = calculate_weighted_return([tsy_1m, tsy_3m, tsy_6m])

    # Create instrument objects
    voo = InstrumentReturns("VOO", voo_1m, voo_3m, voo_6m, voo_weighted)
    vxus = InstrumentReturns("VXUS", vxus_1m, vxus_3m, vxus_6m, vxus_weighted)
    treasury = InstrumentReturns("Treasury", tsy_1m, tsy_3m, tsy_6m, tsy_weighted)

    # Determine winner
    winners = determine_winner(voo, vxus, treasury)

    # Output results
    output = format_output(voo, vxus, treasury, winners)
    print(output)


if __name__ == "__main__":
    main()

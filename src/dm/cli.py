"""CLI entry point."""

import sys
import warnings
from datetime import date

from dateutil.relativedelta import relativedelta

from dm.data import TwelveDataFallbackWarning, get_price_history, get_tbill_rates
from dm.signals import (
    LOOKBACKS,
    SignalResult,
    accumulate_rf_returns,
    anchor_month_end,
    compute_signal,
)

US_TICKER = "VOO"
INTL_TICKER = "VXUS"
BOND_TICKER = "VGIT"

# The signal anchors on the last completed month end and looks back 6 months,
# so the fetch window has to reach into the month 7 months before today.
_HISTORY_MONTHS = 8

_SEPARATOR = "=" * 46


def build_signal(today: date) -> SignalResult:
    """Fetch prices and T-bill rates, then evaluate the dual-momentum rule.

    One price-history request per equity (two TwelveData credits per run); the
    1/3/6-month lookbacks are resolved locally from month-end closes.
    """
    history_start = today - relativedelta(months=_HISTORY_MONTHS)
    us_bars = get_price_history(US_TICKER, history_start, today)
    intl_bars = get_price_history(INTL_TICKER, history_start, today)

    # `compute_signal` anchors both funds on the latest month present in BOTH
    # series, so the risk-free windows have to follow that shared anchor too.
    us_anchor, _ = anchor_month_end(us_bars, today)
    intl_anchor, _ = anchor_month_end(intl_bars, today)
    anchor_date = min(us_anchor, intl_anchor)

    rates = get_tbill_rates(anchor_date - relativedelta(months=_HISTORY_MONTHS), today)
    rf_returns = accumulate_rf_returns(rates, anchor_date)

    return compute_signal(
        us_bars,
        intl_bars,
        rf_returns,
        today,
        us_ticker=US_TICKER,
        intl_ticker=INTL_TICKER,
        bond_ticker=BOND_TICKER,
    )


def format_output(result: SignalResult) -> str:
    """Render a signal result as the report printed by `dm`."""
    lines = [
        "Dual Momentum Analysis",
        f"As of: {result.as_of} (month-end close)",
        _SEPARATOR,
        "",
    ]

    blocks = [
        (f"{US_TICKER}:", result.us_returns, result.us_score),
        (f"{INTL_TICKER}:", result.intl_returns, result.intl_score),
        ("Risk-free (3-month T-bill):", result.rf_returns, result.rf_score),
    ]
    for heading, returns, score in blocks:
        lines.append(heading)
        for months in LOOKBACKS:
            lines.append(f"  {months}-Month: {_pct(returns[months])}")
        lines.append(f"  Score:   {_pct(score)}")
        lines.append("")

    loser, loser_score = (
        (INTL_TICKER, result.intl_score)
        if result.relative_winner == US_TICKER
        else (US_TICKER, result.us_score)
    )
    winner_score = max(result.us_score, result.intl_score)

    lines.append(_SEPARATOR)
    lines.append(
        f"Relative momentum: {result.relative_winner} {_pct(winner_score).strip()} "
        f"beats {loser} {_pct(loser_score).strip()}"
    )
    if result.signal == BOND_TICKER:
        lines.append(
            f"Absolute momentum: {result.relative_winner} "
            f"{_pct(winner_score).strip()} is below the risk-free "
            f"{_pct(result.rf_score).strip()} -> out of the market"
        )
    else:
        lines.append(
            f"Absolute momentum: {result.relative_winner} "
            f"{_pct(winner_score).strip()} clears the risk-free "
            f"{_pct(result.rf_score).strip()} -> stay in the market"
        )
    lines.append(f"Signal: {result.signal} (hold from {result.as_of})")

    return "\n".join(lines)


def _pct(value: float) -> str:
    return f"{value * 100:>7.2f}%"


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


def main(today: date | None = None):
    """Main entry point for the dm CLI."""
    _configure_warnings()

    print(format_output(build_signal(today or date.today())))


if __name__ == "__main__":
    main()

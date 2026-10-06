"""CLI entry point."""

import argparse
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
    compute_signal_trailing,
)

US_TICKER = "VOO"
INTL_TICKER = "VXUS"
BOND_TICKER = "VGIT"

# Lookbacks reach 6 months behind the anchor (and, in month-end mode, the
# anchor can sit a month behind today); 8 months covers both with margin.
_HISTORY_MONTHS = 8

_SEPARATOR = "=" * 46


def build_signal(today: date, month_end: bool = False) -> SignalResult:
    """Fetch prices and T-bill rates, then evaluate the dual-momentum rule.

    One price-history request per equity (two TwelveData credits per run); the
    lookbacks are resolved locally. By default the 1/3/6-month windows trail
    back from the latest close on or before `today`; with `month_end`, they are
    PV's month-end-to-month-end windows at the last completed month end.
    """
    history_start = today - relativedelta(months=_HISTORY_MONTHS)
    us_bars = get_price_history(US_TICKER, history_start, today)
    intl_bars = get_price_history(INTL_TICKER, history_start, today)
    rates = get_tbill_rates(history_start, today)

    if not month_end:
        return compute_signal_trailing(
            us_bars,
            intl_bars,
            rates,
            today,
            us_ticker=US_TICKER,
            intl_ticker=INTL_TICKER,
            bond_ticker=BOND_TICKER,
        )

    # The month-end engine anchors both funds on the latest month end present
    # in BOTH series, so the risk-free windows have to follow that shared
    # anchor too.
    us_anchor, _ = anchor_month_end(us_bars, today)
    intl_anchor, _ = anchor_month_end(intl_bars, today)
    rf_returns = accumulate_rf_returns(rates, min(us_anchor, intl_anchor))

    return compute_signal(
        us_bars,
        intl_bars,
        rf_returns,
        today,
        us_ticker=US_TICKER,
        intl_ticker=INTL_TICKER,
        bond_ticker=BOND_TICKER,
    )


def format_output(result: SignalResult, month_end: bool = False) -> str:
    """Render a signal result as the report printed by `dm`."""
    anchor_label = "month-end close" if month_end else "latest close, trailing windows"
    window_starts = ", ".join(
        f"{months}M {result.window_starts[months]}" for months in LOOKBACKS
    )
    lines = [
        "Dual Momentum Analysis",
        f"As of: {result.as_of} ({anchor_label})",
        f"Windows from: {window_starts}",
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
    if month_end:
        lines.append(f"Signal: {result.signal} (hold from {result.as_of})")
    else:
        lines.append(f"Signal: {result.signal} (as of {result.as_of})")

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


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="dm",
        description="Print the dual-momentum signal: VOO, VXUS, or VGIT.",
    )
    parser.add_argument(
        "--month-end",
        action="store_true",
        help="evaluate Portfolio Visualizer's month-end signal (windows ending "
        "at the last completed month-end close) instead of trailing windows "
        "ending at the latest close",
    )
    return parser.parse_args(argv)


def main(today: date | None = None, argv: list[str] | None = None):
    """Main entry point for the dm CLI."""
    _configure_warnings()

    args = _parse_args(argv)
    result = build_signal(today or date.today(), month_end=args.month_end)
    print(format_output(result, month_end=args.month_end))


if __name__ == "__main__":
    main()

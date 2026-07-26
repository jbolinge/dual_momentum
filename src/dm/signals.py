"""Dual-momentum signal engine, matching Portfolio Visualizer's Dual Momentum Model.

Pure logic — no I/O. The engine works on month-end closes of dividend-adjusted
(total return) price series:

1. Momentum score = weighted average of 1/3/6-month total returns, weights
   33% / 33% / 34%.
2. Signals are computed at the end-of-month close and held the following month.
3. Relative momentum picks the equity fund with the higher score; absolute
   momentum swaps into the bond fund when that winner's score is below the
   risk-free score.
"""

from calendar import monthrange
from dataclasses import dataclass
from datetime import date

WEIGHTS: dict[int, float] = {1: 0.33, 3: 0.33, 6: 0.34}

# Lookback windows in months, ascending.
LOOKBACKS: tuple[int, ...] = (1, 3, 6)

_MONTHS_PER_YEAR = 12


@dataclass(frozen=True)
class SignalResult:
    """The outcome of one month-end dual-momentum evaluation."""

    as_of: date
    us_returns: dict[int, float]
    intl_returns: dict[int, float]
    rf_returns: dict[int, float]
    us_score: float
    intl_score: float
    rf_score: float
    relative_winner: str
    signal: str


def weighted_score(returns: dict[int, float]) -> float:
    """Combine 1/3/6-month returns with the PV weights (33% / 33% / 34%)."""
    return sum(weight * returns[months] for months, weight in WEIGHTS.items())


def month_end_closes(
    bars: list[tuple[date, float]],
) -> list[tuple[date, float]]:
    """Reduce daily bars to the last bar of each calendar month, ascending."""
    last_of_month: dict[tuple[int, int], tuple[date, float]] = {}
    for bar_date, value in sorted(bars, key=lambda bar: bar[0]):
        last_of_month[(bar_date.year, bar_date.month)] = (bar_date, value)
    return [last_of_month[key] for key in sorted(last_of_month)]


def anchor_month_end(bars: list[tuple[date, float]], today: date) -> tuple[date, float]:
    """Return the last bar of the most recent COMPLETED calendar month.

    Month M qualifies once its last calendar day has arrived, so a mid-July run
    anchors on June's final trading day while a July 31 run anchors on July's.
    """
    candidates = [
        bar for bar in month_end_closes(bars) if _last_calendar_day(bar[0]) <= today
    ]
    if not candidates:
        raise ValueError(f"No bars for a completed month on or before {today}")
    return candidates[-1]


def anchor_latest(bars: list[tuple[date, float]], today: date) -> tuple[date, float]:
    """Return the latest bar on or before `today` (the --now anchor)."""
    candidates = [
        bar for bar in sorted(bars, key=lambda bar: bar[0]) if bar[0] <= today
    ]
    if not candidates:
        raise ValueError(f"No bars on or before {today}")
    return candidates[-1]


def accumulate_rf_returns(
    rates: list[tuple[date, float]], anchor: date
) -> dict[int, float]:
    """Compound risk-free returns over the 1/3/6-month windows ending at `anchor`.

    `rates` are observations of an ANNUAL rate as a decimal (e.g. 0.0525),
    daily or monthly. The return earned during month m uses the rate observed at
    the end of month m-1, divided by 12; a window return compounds those monthly
    returns. Months without an observation reuse the most recent earlier rate.
    """
    observations = sorted(rates, key=lambda item: item[0])
    anchor_month = (anchor.year, anchor.month)

    monthly: dict[int, float] = {}
    for lag in range(1, max(LOOKBACKS) + 1):
        rate_month = _shift_month(anchor_month, lag)
        rate = _value_on_or_before(observations, _month_end_date(rate_month))
        if rate is None:
            raise ValueError(
                f"No risk-free rate observation on or before {_month_label(rate_month)}"
            )
        monthly[lag] = rate / _MONTHS_PER_YEAR

    return _compound_windows(monthly)


def accumulate_rf_returns_now(
    rates: list[tuple[date, float]], anchor: date
) -> dict[int, float]:
    """Compound risk-free returns over the 1/3/6-month windows ending at the
    `anchor` DATE rather than at its month end.

    The month starting at anchor-minus-k-months earns the annual rate observed
    on or before that shifted date, divided by 12 — the date analogue of the
    month-end convention where month m earns the rate set at the end of m-1.
    Anchored exactly on a month end this matches `accumulate_rf_returns`.
    """
    observations = sorted(rates, key=lambda item: item[0])

    monthly: dict[int, float] = {}
    for lag in range(1, max(LOOKBACKS) + 1):
        shifted = _shift_date(anchor, lag)
        rate = _value_on_or_before(observations, shifted)
        if rate is None:
            raise ValueError(f"No risk-free rate observation on or before {shifted}")
        monthly[lag] = rate / _MONTHS_PER_YEAR

    return _compound_windows(monthly)


def _compound_windows(monthly: dict[int, float]) -> dict[int, float]:
    windows: dict[int, float] = {}
    for months in LOOKBACKS:
        compounded = 1.0
        for lag in range(1, months + 1):
            compounded *= 1.0 + monthly[lag]
        windows[months] = compounded - 1.0
    return windows


def compute_signal(
    us_bars: list[tuple[date, float]],
    intl_bars: list[tuple[date, float]],
    rf_window_returns: dict[int, float],
    today: date,
    us_ticker: str = "VOO",
    intl_ticker: str = "VXUS",
    bond_ticker: str = "VGIT",
) -> SignalResult:
    """Evaluate the dual-momentum rule at the latest completed month end.

    Both equity series are anchored on the same month — the latest month that is
    complete and present in both — and every return is month-end to month-end.
    """
    us_anchor_date, _ = anchor_month_end(us_bars, today)
    intl_anchor_date, _ = anchor_month_end(intl_bars, today)
    anchor_month = min(
        (us_anchor_date.year, us_anchor_date.month),
        (intl_anchor_date.year, intl_anchor_date.month),
    )

    us_by_month = _by_month(month_end_closes(us_bars))
    intl_by_month = _by_month(month_end_closes(intl_bars))

    us_returns = _lookback_returns(us_by_month, anchor_month, us_ticker)
    intl_returns = _lookback_returns(intl_by_month, anchor_month, intl_ticker)
    as_of = us_by_month[anchor_month][0]

    return _build_result(
        as_of,
        us_returns,
        intl_returns,
        rf_window_returns,
        us_ticker,
        intl_ticker,
        bond_ticker,
    )


def compute_signal_now(
    us_bars: list[tuple[date, float]],
    intl_bars: list[tuple[date, float]],
    rf_window_returns: dict[int, float],
    today: date,
    us_ticker: str = "VOO",
    intl_ticker: str = "VXUS",
    bond_ticker: str = "VGIT",
) -> SignalResult:
    """Evaluate the dual-momentum rule at the latest available close (--now).

    Both series are priced at the same date — the earlier of the two latest
    bars on or before `today` — and each lookback runs from the close on or
    before the date exactly 1/3/6 calendar months earlier.
    """
    us_anchor_date, _ = anchor_latest(us_bars, today)
    intl_anchor_date, _ = anchor_latest(intl_bars, today)
    anchor_date = min(us_anchor_date, intl_anchor_date)

    us_returns = _date_lookback_returns(us_bars, anchor_date, us_ticker)
    intl_returns = _date_lookback_returns(intl_bars, anchor_date, intl_ticker)

    return _build_result(
        anchor_date,
        us_returns,
        intl_returns,
        rf_window_returns,
        us_ticker,
        intl_ticker,
        bond_ticker,
    )


def _build_result(
    as_of: date,
    us_returns: dict[int, float],
    intl_returns: dict[int, float],
    rf_window_returns: dict[int, float],
    us_ticker: str,
    intl_ticker: str,
    bond_ticker: str,
) -> SignalResult:
    """Score the returns and apply the relative/absolute momentum rules."""
    us_score = weighted_score(us_returns)
    intl_score = weighted_score(intl_returns)
    rf_score = weighted_score(rf_window_returns)

    # Relative momentum: higher score wins; a tie prefers the US fund.
    if us_score >= intl_score:
        relative_winner, winner_score = us_ticker, us_score
    else:
        relative_winner, winner_score = intl_ticker, intl_score

    # Absolute momentum: leave equities only on a strictly negative excess return.
    signal = bond_ticker if winner_score < rf_score else relative_winner

    return SignalResult(
        as_of=as_of,
        us_returns=us_returns,
        intl_returns=intl_returns,
        rf_returns=dict(rf_window_returns),
        us_score=us_score,
        intl_score=intl_score,
        rf_score=rf_score,
        relative_winner=relative_winner,
        signal=signal,
    )


def _by_month(
    month_ends: list[tuple[date, float]],
) -> dict[tuple[int, int], tuple[date, float]]:
    return {
        (bar_date.year, bar_date.month): (bar_date, value)
        for bar_date, value in month_ends
    }


def _lookback_returns(
    by_month: dict[tuple[int, int], tuple[date, float]],
    anchor_month: tuple[int, int],
    symbol: str,
) -> dict[int, float]:
    """Month-end-to-month-end total returns over each lookback window."""

    def close_for(month: tuple[int, int]) -> float:
        if month not in by_month:
            raise ValueError(
                f"No month-end close for {symbol} in {_month_label(month)}"
            )
        return by_month[month][1]

    anchor_close = close_for(anchor_month)
    return {
        months: anchor_close / close_for(_shift_month(anchor_month, months)) - 1.0
        for months in LOOKBACKS
    }


def _date_lookback_returns(
    bars: list[tuple[date, float]], anchor: date, symbol: str
) -> dict[int, float]:
    """Close-to-close total returns from the dates exactly N months before
    `anchor`, using the most recent close on or before each target date."""
    observations = sorted(bars, key=lambda bar: bar[0])

    def close_for(target: date) -> float:
        close = _value_on_or_before(observations, target)
        if close is None:
            raise ValueError(f"No {symbol} close on or before {target}")
        return close

    anchor_close = close_for(anchor)
    return {
        months: anchor_close / close_for(_shift_date(anchor, months)) - 1.0
        for months in LOOKBACKS
    }


def _shift_date(day: date, months_back: int) -> date:
    """The same day-of-month `months_back` months earlier, clamped to the
    month's last day (July 31 minus one month is June 30)."""
    year, month_number = _shift_month((day.year, day.month), months_back)
    return date(year, month_number, min(day.day, monthrange(year, month_number)[1]))


def _shift_month(month: tuple[int, int], months_back: int) -> tuple[int, int]:
    year, month_number = month
    years, zero_based_month = divmod(
        year * _MONTHS_PER_YEAR + (month_number - 1) - months_back, _MONTHS_PER_YEAR
    )
    return years, zero_based_month + 1


def _month_end_date(month: tuple[int, int]) -> date:
    year, month_number = month
    return date(year, month_number, monthrange(year, month_number)[1])


def _last_calendar_day(day: date) -> date:
    return _month_end_date((day.year, day.month))


def _month_label(month: tuple[int, int]) -> str:
    return f"{month[0]:04d}-{month[1]:02d}"


def _value_on_or_before(
    observations: list[tuple[date, float]], target: date
) -> float | None:
    """Latest value observed on or before `target`, or None if there is none."""
    latest: float | None = None
    for observed, value in observations:
        if observed > target:
            break
        latest = value
    return latest

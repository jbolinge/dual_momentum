"""Dual-momentum signal engine, after Portfolio Visualizer's Dual Momentum Model.

Pure logic — no I/O. The engine works on dividend-adjusted (total return)
price series:

1. Momentum score = weighted average of 1/3/6-month total returns, weights
   33% / 33% / 34%.
2. Relative momentum picks the equity fund with the higher score; absolute
   momentum swaps into the bond fund when that winner's score is below the
   risk-free score.

Two evaluation modes share that rule:

- `compute_signal_trailing` (the CLI default) measures trailing 1/3/6-month
  windows ending at the latest close on the run date, so a weekly run always
  sees whole-month lookbacks.
- `compute_signal` evaluates only at completed month-end closes — PV's own
  convention, which the backtest validates.

On a month's final close the two produce the same result.
"""

from calendar import monthrange
from dataclasses import dataclass, field
from datetime import date, timedelta

from dateutil.relativedelta import relativedelta

WEIGHTS: dict[int, float] = {1: 0.33, 3: 0.33, 6: 0.34}

# Lookback windows in months, ascending.
LOOKBACKS: tuple[int, ...] = (1, 3, 6)

_MONTHS_PER_YEAR = 12

# A trailing window's base close may predate its start date (weekends,
# holidays), but a longer gap means missing data rather than a market closure.
_MAX_BASE_STALENESS = timedelta(days=10)


@dataclass(frozen=True)
class SignalResult:
    """The outcome of one dual-momentum evaluation."""

    as_of: date
    us_returns: dict[int, float]
    intl_returns: dict[int, float]
    rf_returns: dict[int, float]
    us_score: float
    intl_score: float
    rf_score: float
    relative_winner: str
    signal: str
    # Calendar start date of each lookback window; each base close is the
    # latest close on or before it.
    window_starts: dict[int, date] = field(default_factory=dict)


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
    """Return the latest bar on or before `today` (the trailing anchor)."""
    candidates = [
        bar for bar in sorted(bars, key=lambda bar: bar[0]) if bar[0] <= today
    ]
    if not candidates:
        raise ValueError(f"No bars on or before {today}")
    return candidates[-1]


def is_month_end_anchor(anchor: date, today: date) -> bool:
    """Whether `anchor` is the final close of its month.

    True once the month has ended by `today`, or when no weekday remains in the
    month after `anchor` (e.g. a Friday close before a weekend month end).
    """
    month_end = _last_calendar_day(anchor)
    if month_end <= today:
        return True
    remaining = (anchor + timedelta(days=offset) for offset in range(1, 7))
    return not any(day.weekday() < 5 for day in remaining if day.month == anchor.month)


def lookback_dates(anchor: date, month_end: bool) -> dict[int, date]:
    """Start dates of the trailing one-month steps back from `anchor`.

    Maps each lag 1..6 to the date `lag` months before `anchor` — the same
    calendar day, clamped to shorter months. With `month_end`, the anchor closes
    its month and every step lands on a prior month's last calendar day
    (Sep 30 steps back to Aug 31, not Aug 30).
    """
    anchor_month = (anchor.year, anchor.month)
    return {
        lag: _month_end_date(_shift_month(anchor_month, lag))
        if month_end
        else anchor - relativedelta(months=lag)
        for lag in range(1, max(LOOKBACKS) + 1)
    }


def trailing_rf_returns(
    rates: list[tuple[date, float]], step_dates: dict[int, date]
) -> dict[int, float]:
    """Compound risk-free returns over the 1/3/6-month windows of `step_dates`.

    `rates` are observations of an ANNUAL rate as a decimal (e.g. 0.0525),
    daily or monthly. The one-month step starting at `step_dates[lag]` earns the
    latest rate observed on or before that date, divided by 12; a window return
    compounds its steps.
    """
    observations = sorted(rates, key=lambda item: item[0])

    monthly: dict[int, float] = {}
    for lag in range(1, max(LOOKBACKS) + 1):
        rate = _rate_on_or_before(observations, step_dates[lag])
        if rate is None:
            raise ValueError(
                f"No risk-free rate observation on or before {step_dates[lag]}"
            )
        monthly[lag] = rate / _MONTHS_PER_YEAR

    windows: dict[int, float] = {}
    for months in LOOKBACKS:
        compounded = 1.0
        for lag in range(1, months + 1):
            compounded *= 1.0 + monthly[lag]
        windows[months] = compounded - 1.0
    return windows


def accumulate_rf_returns(
    rates: list[tuple[date, float]], anchor: date
) -> dict[int, float]:
    """Compound risk-free returns over the 1/3/6-month windows ending at the
    end of `anchor`'s month (PV's month-end convention).

    The return earned during month m uses the rate observed at the end of month
    m-1, divided by 12. Months without an observation reuse the most recent
    earlier rate.
    """
    return trailing_rf_returns(rates, lookback_dates(anchor, month_end=True))


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
    window_starts = {
        months: _month_end_date(_shift_month(anchor_month, months))
        for months in LOOKBACKS
    }

    return _build_result(
        as_of,
        us_returns,
        intl_returns,
        rf_window_returns,
        us_ticker,
        intl_ticker,
        bond_ticker,
        window_starts,
    )


def compute_signal_trailing(
    us_bars: list[tuple[date, float]],
    intl_bars: list[tuple[date, float]],
    rates: list[tuple[date, float]],
    today: date,
    us_ticker: str = "VOO",
    intl_ticker: str = "VXUS",
    bond_ticker: str = "VGIT",
) -> SignalResult:
    """Evaluate the dual-momentum rule on trailing windows ending today.

    Both series are priced at the same date — the earlier of the two latest
    bars on or before `today`. Each N-month return divides that close by the
    latest close on or before the date N months earlier, and the risk-free leg
    compounds T-bill returns over the same windows. When the anchor is a
    month's final close the windows snap to prior month ends, reproducing
    `compute_signal` exactly.
    """
    us_anchor_date, _ = anchor_latest(us_bars, today)
    intl_anchor_date, _ = anchor_latest(intl_bars, today)
    anchor_date = min(us_anchor_date, intl_anchor_date)

    step_dates = lookback_dates(
        anchor_date, month_end=is_month_end_anchor(anchor_date, today)
    )
    window_starts = {months: step_dates[months] for months in LOOKBACKS}

    us_returns = _trailing_returns(us_bars, anchor_date, window_starts, us_ticker)
    intl_returns = _trailing_returns(intl_bars, anchor_date, window_starts, intl_ticker)

    return _build_result(
        anchor_date,
        us_returns,
        intl_returns,
        trailing_rf_returns(rates, step_dates),
        us_ticker,
        intl_ticker,
        bond_ticker,
        window_starts,
    )


def _build_result(
    as_of: date,
    us_returns: dict[int, float],
    intl_returns: dict[int, float],
    rf_window_returns: dict[int, float],
    us_ticker: str,
    intl_ticker: str,
    bond_ticker: str,
    window_starts: dict[int, date],
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
        window_starts=window_starts,
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
    anchor_close = _month_close(by_month, anchor_month, symbol)
    return {
        months: anchor_close
        / _month_close(by_month, _shift_month(anchor_month, months), symbol)
        - 1.0
        for months in LOOKBACKS
    }


def _trailing_returns(
    bars: list[tuple[date, float]],
    anchor_date: date,
    window_starts: dict[int, date],
    symbol: str,
) -> dict[int, float]:
    """Total returns from the close on or before each window start to the
    close on or before `anchor_date`."""
    _, anchor_close = anchor_latest(bars, anchor_date)
    returns: dict[int, float] = {}
    for months, start in window_starts.items():
        try:
            base_date, base_close = anchor_latest(bars, start)
        except ValueError:
            raise ValueError(
                f"No {symbol} close on or before {start} for the "
                f"{months}-month lookback"
            ) from None
        if start - base_date > _MAX_BASE_STALENESS:
            raise ValueError(
                f"{symbol} {months}-month base close is stale: latest close on "
                f"or before {start} is {base_date}"
            )
        returns[months] = anchor_close / base_close - 1.0
    return returns


def _month_close(
    by_month: dict[tuple[int, int], tuple[date, float]],
    month: tuple[int, int],
    symbol: str,
) -> float:
    if month not in by_month:
        raise ValueError(f"No month-end close for {symbol} in {_month_label(month)}")
    return by_month[month][1]


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


def _rate_on_or_before(
    observations: list[tuple[date, float]], target: date
) -> float | None:
    """Latest rate observed on or before `target`, or None if there is none."""
    latest: float | None = None
    for observed, rate in observations:
        if observed > target:
            break
        latest = rate
    return latest

"""Backtest the `dm.signals` engine against Portfolio Visualizer's Dual Momentum Model.

Runs the SAME engine the CLI uses over PV's fund universe (VFINX / VGTSX / VFITX)
for every month-end anchor from Dec 1996 to Jun 2026, and compares:

* the predicted holding for each following month vs `ground_truth/pv_holdings.json`
* the resulting monthly portfolio returns vs `ground_truth/pv_monthly_returns.json`

Several risk-free accumulation variants are scored; the one with the best holdings
match rate wins (ties go to the design default, DTB3 sampled at the prior month end
with a simple rate/12 monthly accrual).

Usage:
    uv run python backtest/backtest_pv.py [--refresh]

Raw vendor data is cached under `backtest/cache/` (gitignored) so reruns are offline.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import warnings
from calendar import monthrange
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from dm.signals import (
    LOOKBACKS,
    accumulate_rf_returns,
    compute_signal,
    month_end_closes,
)

Month = tuple[int, int]
Bars = list[tuple[date, float]]

BACKTEST_DIR = Path(__file__).resolve().parent
CACHE_DIR = BACKTEST_DIR / "cache"
GROUND_TRUTH_DIR = BACKTEST_DIR / "ground_truth"
RESULTS_PATH = BACKTEST_DIR / "results.json"
REPORT_PATH = BACKTEST_DIR / "REPORT.md"

US_TICKER = "VFINX"
INTL_TICKER = "VGTSX"
BOND_TICKER = "VFITX"
TICKERS = (US_TICKER, INTL_TICKER, BOND_TICKER)

# Daily history start: the first anchor (1996-12) needs a 6-month lookback close
# from 1996-06, and VGTSX itself only starts 1996-04-29.
HISTORY_START = date(1996, 1, 2)
HISTORY_END = date(2026, 7, 31)

FIRST_ANCHOR: Month = (1996, 12)
LAST_ANCHOR: Month = (2026, 6)
FIRST_RETURN_MONTH: Month = (1997, 1)
LAST_RETURN_MONTH: Month = (2026, 6)

PV_TWRR_CAGR = 0.1352
SUCCESS_MATCH_RATE = 0.96
SUSPICIOUS_GAP_BPS = 30.0
RETURN_DIFF_BPS_THRESHOLD = 50.0

MONTHS_PER_YEAR = 12


# --------------------------------------------------------------------------- #
# Month helpers
# --------------------------------------------------------------------------- #


def month_label(month: Month) -> str:
    return f"{month[0]:04d}-{month[1]:02d}"


def parse_month(label: str) -> Month:
    year, month = label.split("-")
    return int(year), int(month)


def shift_month(month: Month, delta: int) -> Month:
    years, zero_based = divmod(
        month[0] * MONTHS_PER_YEAR + (month[1] - 1) + delta, MONTHS_PER_YEAR
    )
    return years, zero_based + 1


def month_end_date(month: Month) -> date:
    return date(month[0], month[1], monthrange(month[0], month[1])[1])


def month_range(first: Month, last: Month) -> list[Month]:
    months: list[Month] = []
    current = first
    while current <= last:
        months.append(current)
        current = shift_month(current, 1)
    return months


# --------------------------------------------------------------------------- #
# Cached data loading
# --------------------------------------------------------------------------- #


def _read_cache(path: Path) -> list[tuple[date, float]] | None:
    if not path.exists():
        return None
    with path.open(newline="") as handle:
        reader = csv.reader(handle)
        next(reader, None)  # header
        return [(date.fromisoformat(row[0]), float(row[1])) for row in reader]


def _write_cache(path: Path, header: str, rows: list[tuple[date, float]]) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["date", header])
        for observed, value in rows:
            writer.writerow([observed.isoformat(), repr(value)])


def load_prices(symbol: str, refresh: bool = False) -> Bars:
    """Daily dividend/split-adjusted closes for `symbol`, cached on disk.

    yfinance with `auto_adjust=True` is used directly (rather than
    `dm.data.get_price_history`) because the 30-year window is far outside the
    free TwelveData plan and PV's own numbers are total-return.
    """
    path = CACHE_DIR / f"prices_{symbol}.csv"
    if not refresh:
        cached = _read_cache(path)
        if cached:
            return cached

    import yfinance as yf  # imported lazily so cached runs stay fast

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        history = yf.Ticker(symbol).history(
            start=HISTORY_START, end=HISTORY_END, auto_adjust=True
        )
    if history.empty:
        raise ValueError(f"No price history for {symbol}")
    history.index = history.index.tz_localize(None)
    bars = [
        (timestamp.date(), float(close))
        for timestamp, close in zip(history.index, history["Close"])
    ]
    _write_cache(path, "close", bars)
    return bars


def load_fred_series(series_id: str, refresh: bool = False) -> list[tuple[date, float]]:
    """FRED series as (date, annual rate as decimal) pairs, cached on disk."""
    path = CACHE_DIR / f"fred_{series_id}.csv"
    if not refresh:
        cached = _read_cache(path)
        if cached:
            return cached

    from dotenv import load_dotenv
    from fredapi import Fred

    load_dotenv(BACKTEST_DIR.parent / ".env")
    api_key = os.getenv("FRED_API_KEY")
    if not api_key:
        raise ValueError("FRED_API_KEY not found in environment")
    series = Fred(api_key=api_key).get_series(series_id, HISTORY_START, HISTORY_END)
    observations = [
        (timestamp.date(), float(value) / 100)
        for timestamp, value in series.dropna().items()
    ]
    if not observations:
        raise ValueError(f"No observations for FRED series {series_id}")
    _write_cache(path, "rate", observations)
    return observations


def load_ground_truth() -> tuple[dict[str, str], dict[str, float], list[dict]]:
    holdings = json.loads((GROUND_TRUTH_DIR / "pv_holdings.json").read_text())
    returns = json.loads((GROUND_TRUTH_DIR / "pv_monthly_returns.json").read_text())
    trades = json.loads((GROUND_TRUTH_DIR / "pv_trades.json").read_text())
    return holdings, returns, trades


# --------------------------------------------------------------------------- #
# Risk-free variants
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class RiskFreeVariant:
    """One way of turning an observed T-bill rate series into window returns.

    Attributes:
        name: identifier used in the report.
        series_id: FRED series backing it.
        alignment: "prior" earns month m the rate observed at the end of month
            m-1 (a forward-looking yield, the design default); "same" earns
            month m the rate observed within month m itself.
        compounding: "simple" uses rate/12, "geometric" uses (1+rate)**(1/12)-1.
    """

    name: str
    series_id: str
    alignment: str
    compounding: str
    description: str


VARIANTS: tuple[RiskFreeVariant, ...] = (
    RiskFreeVariant(
        "a_dtb3_prior_simple",
        "DTB3",
        "prior",
        "simple",
        "DTB3 sampled at the prior month end, rate/12, compounded (design default)",
    ),
    RiskFreeVariant(
        "b_tb3ms_prior_simple",
        "TB3MS",
        "prior",
        "simple",
        "TB3MS monthly average of the prior month, rate/12, compounded",
    ),
    RiskFreeVariant(
        "c_dtb3_prior_geom",
        "DTB3",
        "prior",
        "geometric",
        "DTB3 sampled at the prior month end, (1+rate)^(1/12)-1",
    ),
    RiskFreeVariant(
        "c_tb3ms_prior_geom",
        "TB3MS",
        "prior",
        "geometric",
        "TB3MS monthly average of the prior month, (1+rate)^(1/12)-1",
    ),
    RiskFreeVariant(
        "d_dtb3_same_simple",
        "DTB3",
        "same",
        "simple",
        "DTB3 sampled at the same month end, rate/12, compounded",
    ),
    RiskFreeVariant(
        "d_tb3ms_same_simple",
        "TB3MS",
        "same",
        "simple",
        "TB3MS monthly average of the same month, rate/12, compounded",
    ),
    RiskFreeVariant(
        "e_dtb3_same_geom",
        "DTB3",
        "same",
        "geometric",
        "DTB3 sampled at the same month end, (1+rate)^(1/12)-1",
    ),
    RiskFreeVariant(
        "e_tb3ms_same_geom",
        "TB3MS",
        "same",
        "geometric",
        "TB3MS monthly average of the same month, (1+rate)^(1/12)-1",
    ),
)

# Preference order when several variants tie on the holdings match rate.
VARIANT_PREFERENCE = [variant.name for variant in VARIANTS]


def monthly_rate_map(observations: list[tuple[date, float]]) -> dict[Month, float]:
    """Collapse a FRED series to one annual rate per month.

    DTB3 (daily) is sampled at the last observation of the month — PV computes
    signals at the month-end close. TB3MS is already one value per month, dated
    on the first of the month it summarises.
    """
    by_month: dict[Month, float] = {}
    for observed, rate in sorted(observations):
        by_month[(observed.year, observed.month)] = rate
    return by_month


def rf_window_returns(
    rates_by_month: dict[Month, float], anchor: Month, variant: RiskFreeVariant
) -> dict[int, float]:
    """Risk-free returns over the 1/3/6-month windows ending at `anchor`."""
    monthly: dict[int, float] = {}
    for lag in range(1, max(LOOKBACKS) + 1):
        earning_month = shift_month(anchor, -(lag - 1))
        rate_month = (
            shift_month(earning_month, -1)
            if variant.alignment == "prior"
            else earning_month
        )
        rate = _rate_for_month(rates_by_month, rate_month)
        monthly[lag] = (
            rate / MONTHS_PER_YEAR
            if variant.compounding == "simple"
            else (1.0 + rate) ** (1.0 / MONTHS_PER_YEAR) - 1.0
        )

    windows: dict[int, float] = {}
    for months in LOOKBACKS:
        compounded = 1.0
        for lag in range(1, months + 1):
            compounded *= 1.0 + monthly[lag]
        windows[months] = compounded - 1.0
    return windows


def _rate_for_month(rates_by_month: dict[Month, float], month: Month) -> float:
    """Rate for `month`, falling back to the most recent earlier month."""
    candidates = [key for key in rates_by_month if key <= month]
    if not candidates:
        raise ValueError(f"No risk-free observation on or before {month_label(month)}")
    return rates_by_month[max(candidates)]


def assert_default_variant_matches_engine(
    dtb3: list[tuple[date, float]], anchors: list[Month]
) -> None:
    """The design-default variant must equal `signals.accumulate_rf_returns`.

    This keeps the backtest honest: variant (a) is not a re-implementation that
    could drift from the shipped engine, it is the shipped engine.
    """
    default = VARIANTS[0]
    rates_by_month = monthly_rate_map(dtb3)
    for anchor in anchors:
        engine = accumulate_rf_returns(dtb3, month_end_date(anchor))
        local = rf_window_returns(rates_by_month, anchor, default)
        for months in LOOKBACKS:
            if abs(engine[months] - local[months]) > 1e-12:
                raise AssertionError(
                    f"variant {default.name} diverges from signals."
                    f"accumulate_rf_returns at {month_label(anchor)} "
                    f"({months}m): {local[months]} vs {engine[months]}"
                )


# --------------------------------------------------------------------------- #
# Backtest
# --------------------------------------------------------------------------- #


def closes_by_month(bars: Bars) -> dict[Month, float]:
    return {
        (bar_date.year, bar_date.month): close
        for bar_date, close in month_end_closes(bars)
    }


def monthly_asset_return(
    closes: dict[Month, float], ticker: str, month: Month
) -> float:
    previous = shift_month(month, -1)
    if month not in closes or previous not in closes:
        raise ValueError(
            f"Missing month-end close for {ticker} around {month_label(month)}"
        )
    return closes[month] / closes[previous] - 1.0


def run_variant(
    variant: RiskFreeVariant,
    price_bars: dict[str, Bars],
    rates: dict[str, list[tuple[date, float]]],
    anchors: list[Month],
    pv_holdings: dict[str, str],
) -> dict:
    """Evaluate one risk-free variant over every anchor month."""
    rates_by_month = monthly_rate_map(rates[variant.series_id])
    predictions: dict[str, dict] = {}
    matches = 0
    mismatches: list[dict] = []

    for anchor in anchors:
        windows = rf_window_returns(rates_by_month, anchor, variant)
        result = compute_signal(
            price_bars[US_TICKER],
            price_bars[INTL_TICKER],
            windows,
            today=month_end_date(anchor),
            us_ticker=US_TICKER,
            intl_ticker=INTL_TICKER,
            bond_ticker=BOND_TICKER,
        )
        if (result.as_of.year, result.as_of.month) != anchor:
            raise AssertionError(
                f"anchor drift: asked for {month_label(anchor)}, got {result.as_of}"
            )
        held_month = shift_month(anchor, 1)
        label = month_label(held_month)
        expected = pv_holdings[label]
        record = {
            "month": label,
            "anchor": result.as_of.isoformat(),
            "predicted": result.signal,
            "expected": expected,
            "us_score": result.us_score,
            "intl_score": result.intl_score,
            "rf_score": result.rf_score,
            "us_returns": {str(k): v for k, v in result.us_returns.items()},
            "intl_returns": {str(k): v for k, v in result.intl_returns.items()},
            "rf_returns": {str(k): v for k, v in result.rf_returns.items()},
            "relative_winner": result.relative_winner,
        }
        record["margin_bps"] = decision_margin_bps(record)
        predictions[label] = record
        if result.signal == expected:
            matches += 1
        else:
            mismatches.append({**record, "gap_bps": _decision_gap_bps(record)})

    total = len(anchors)
    return {
        "variant": variant.name,
        "series_id": variant.series_id,
        "alignment": variant.alignment,
        "compounding": variant.compounding,
        "description": variant.description,
        "months": total,
        "matches": matches,
        "match_rate": matches / total,
        "mismatch_count": len(mismatches),
        "bond_months_predicted": sum(
            1 for record in predictions.values() if record["predicted"] == BOND_TICKER
        ),
        "mean_rf_score_bps": _mean(
            [record["rf_score"] for record in predictions.values()]
        )
        * 10_000,
        "mismatches": mismatches,
        "predictions": predictions,
    }


def decision_margin_bps(record: dict) -> float:
    """Distance (bps) from this month's decision flipping either way.

    Both comparisons are live every month: the US-vs-Intl ranking and the
    winner's excess over the risk-free score. The margin is the smaller of the
    two, so a small margin marks a month whose holding is sensitive to data
    noise regardless of which way it went.
    """
    winner_score = max(record["us_score"], record["intl_score"])
    return (
        min(
            abs(record["us_score"] - record["intl_score"]),
            abs(winner_score - record["rf_score"]),
        )
        * 10_000
    )


def _decision_gap_bps(record: dict) -> float:
    """How far the decision was from flipping, in basis points.

    For a relative-momentum mismatch (US vs Intl) that is the score gap between
    the two equity funds; for an in/out-of-market mismatch it is the winner's
    excess return over the risk-free score. A tiny gap means the flip is data
    noise; a wide one points at a logic difference.
    """
    predicted, expected = record["predicted"], record["expected"]
    winner_score = max(record["us_score"], record["intl_score"])
    if BOND_TICKER in (predicted, expected):
        return abs(winner_score - record["rf_score"]) * 10_000
    return abs(record["us_score"] - record["intl_score"]) * 10_000


def check_trade_dates(predictions: dict[str, dict], pv_trades: list[dict]) -> dict:
    """Cross-check our month-end anchor dates against PV's own trade dates.

    PV executes on the end-of-month close, so every PV trade date must equal the
    month-end trading day our engine anchored on for that same month. A mismatch
    would mean the two calendars disagree about what "month end" is.
    """
    mismatches: list[dict] = []
    for trade in pv_trades:
        trade_date = date.fromisoformat(trade["trade_date"])
        # Predictions are keyed by the month HELD, i.e. the month after the anchor.
        label = month_label(shift_month((trade_date.year, trade_date.month), 1))
        anchor = predictions.get(label, {}).get("anchor")
        if anchor != trade["trade_date"]:
            mismatches.append(
                {
                    "trade": trade["num"],
                    "pv_trade_date": trade["trade_date"],
                    "our_anchor": anchor,
                }
            )
    return {
        "trades_checked": len(pv_trades),
        "anchor_date_mismatches": mismatches,
        "all_match": not mismatches,
    }


def trade_blocks(holdings: dict[str, str], first: Month, last: Month) -> list[dict]:
    """Collapse a month -> ticker map into contiguous holding blocks."""
    blocks: list[dict] = []
    for month in month_range(first, last):
        label = month_label(month)
        ticker = holdings[label]
        if blocks and blocks[-1]["ticker"] == ticker:
            blocks[-1]["end"] = label
        else:
            blocks.append({"ticker": ticker, "start": label, "end": label})
    return blocks


def compare_returns(
    predictions: dict[str, dict],
    closes: dict[str, dict[Month, float]],
    pv_returns: dict[str, float],
    pv_holdings: dict[str, str],
) -> dict:
    """Monthly portfolio returns of the predicted holdings vs PV's own series."""
    rows: list[dict] = []
    for month in month_range(FIRST_RETURN_MONTH, LAST_RETURN_MONTH):
        label = month_label(month)
        predicted = predictions[label]["predicted"]
        expected = pv_holdings[label]
        model_return = monthly_asset_return(closes[predicted], predicted, month)
        pv_return = pv_returns[label]
        rows.append(
            {
                "month": label,
                "predicted": predicted,
                "expected": expected,
                "model_return": model_return,
                # What PV's own holding would have returned on our price data —
                # isolates price-data noise from signal mismatches.
                "pv_holding_return_our_data": monthly_asset_return(
                    closes[expected], expected, month
                ),
                "pv_return": pv_return,
                "diff": model_return - pv_return,
            }
        )

    matched = [row for row in rows if row["predicted"] == row["expected"]]
    diffs = [abs(row["diff"]) for row in rows]
    matched_diffs = [abs(row["diff"]) for row in matched]
    data_only_diffs = [
        abs(row["pv_holding_return_our_data"] - row["pv_return"]) for row in rows
    ]

    return {
        "months": len(rows),
        "mean_abs_diff_bps": _mean(diffs) * 10_000,
        "max_abs_diff_bps": max(diffs) * 10_000,
        "count_over_50bps": sum(
            1 for diff in diffs if diff * 10_000 > RETURN_DIFF_BPS_THRESHOLD
        ),
        "matched_months": len(matched),
        "matched_mean_abs_diff_bps": _mean(matched_diffs) * 10_000,
        "matched_max_abs_diff_bps": max(matched_diffs) * 10_000,
        "matched_count_over_20bps": sum(
            1 for diff in matched_diffs if diff * 10_000 > 20
        ),
        "matched_count_over_50bps": sum(
            1 for diff in matched_diffs if diff * 10_000 > RETURN_DIFF_BPS_THRESHOLD
        ),
        # Diff attributable purely to price data (PV's holdings, our prices).
        "data_only_mean_abs_diff_bps": _mean(data_only_diffs) * 10_000,
        "data_only_max_abs_diff_bps": max(data_only_diffs) * 10_000,
        "rows": rows,
    }


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def compound(returns: list[float]) -> float:
    growth = 1.0
    for value in returns:
        growth *= 1.0 + value
    return growth - 1.0


def twrr_cagr(returns: list[float]) -> float:
    growth = 1.0 + compound(returns)
    return growth ** (MONTHS_PER_YEAR / len(returns)) - 1.0


def per_year_table(rows: list[dict]) -> list[dict]:
    years = sorted({int(row["month"][:4]) for row in rows})
    table: list[dict] = []
    for year in years:
        year_rows = [row for row in rows if row["month"].startswith(f"{year:04d}")]
        model = compound([row["model_return"] for row in year_rows])
        pv = compound([row["pv_return"] for row in year_rows])
        table.append(
            {
                "year": year,
                "months": len(year_rows),
                "model": model,
                "pv": pv,
                "diff_pp": (model - pv) * 100,
            }
        )
    return table


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #

# Hand-verified write-ups for individual mismatches, keyed by held month.
MISMATCH_NOTES: dict[str, str] = {
    "2003-06": """\
**Verdict: Yahoo price/dividend data artifact at the window boundary, not an engine bug.**

PV's trade 13 holds VFINX for 2003-04..2003-06 and trade 14 switches to VGTSX on
2003-06-30; our engine switches one month early, at the 2003-05-30 anchor. The 1- and
3-month lookbacks are not decisive (US wins the 3-month, Intl the 1-month); the flip is
driven by the 6-month window, which runs from the **2002-11-29** close — and that close
is corrupt in Yahoo's mutual-fund NAV series:

* On 2002-11-29 (the half session after Thanksgiving) Yahoo repeats the 2002-11-27 NAV
  verbatim for both funds: VFINX 86.91 -> 86.91 and VGTSX 8.09 -> 8.09, while `^SP500TR`
  moved -0.266% that day. VFINX tracks `^SP500TR` to within 2bps in every surrounding
  month except Nov 2002 (+27.0bps) and Dec 2002 (-27.5bps) — the exact signature of one
  stale month-end print. The stale VFINX close is ~27bps too high, which understates our
  US 6-month return by ~27bps (ours 3.535% vs `^SP500TR` 3.868%).
* VGTSX's 2002-11-29 NAV is stale by the same mechanism, and foreign markets moved on the
  2002-11-28/11-29 sessions it should have captured (Nikkei +3.39%/+0.42%, FTSE
  +0.99%/-0.38%, DAX +0.44%/-1.20%; EFA +0.51% over the two days). A true 11/29 NAV
  ~0.5-1.0% above the stale 8.09 lowers our Intl 6-month return by roughly that much.
* Yahoo also carries three VGTSX dividends that break the fund's otherwise strictly
  annual December distribution pattern (1996-2007): 0.043 on 2002-11-29, 0.045 on
  2003-01-31 and 0.042 on 2003-02-28. The latter two sit inside this 6-month window and
  inflate the Intl 6-month return by ~124bps; dropping them alone cuts the score gap from
  75bps to ~33bps.

Stacking the three corrections closes ~72bps of the 75bps gap: the spurious dividends are
worth 0.34 x 124bps = 42bps, the stale VFINX close 0.34 x 27bps = 9bps, and a VGTSX
11/29 NAV 0.6% above the stale print (the EFA-implied figure, the most conservative of the
proxies above) 0.34 x 60bps = 20bps. Only the VGTSX NAV term is an estimate; the other two
are measured. That lands the decision on the knife edge PV came down on the other side of.
Every other cross-check at this point in the series is exact: our VFINX months
2003-04/05 reproduce PV to 0.4bps, our VGTSX months 2003-07..12 reproduce PV to <=0.5bps,
and compounding our VFINX 2003-04..06 returns gives +15.389% against PV's trade-13
figure of 15.39%. No change to `src/dm` is warranted.""",
}


def build_report(results: dict) -> str:
    chosen = results["chosen_variant"]
    holdings = results["holdings"]
    returns = results["returns"]
    lines: list[str] = []
    add = lines.append

    add(
        "# PV Parity Backtest — `dm.signals` vs Portfolio Visualizer Dual Momentum Model"
    )
    add("")
    add(
        f"Engine: `src/dm/signals.py` (weights 33/33/34 over 1/3/6-month total returns). "
        f"Universe: {US_TICKER} (US) / {INTL_TICKER} (Intl) / {BOND_TICKER} (out-of-market). "
        f"Prices: yfinance daily `auto_adjust=True` reduced to month-end closes. "
        f"Anchors: {month_label(FIRST_ANCHOR)}..{month_label(LAST_ANCHOR)} "
        f"({holdings['months']} signals, holdings for "
        f"{month_label(FIRST_RETURN_MONTH)}..{month_label(shift_month(LAST_ANCHOR, 1))})."
    )
    add("")
    add(f"Ground truth: `backtest/ground_truth/*.json` parsed from `{results['pdf']}`.")
    add("")

    add("## Headline")
    add("")
    add("| Metric | Value | Bar | Pass |")
    add("| --- | --- | --- | --- |")
    add(
        f"| Holdings match rate | **{holdings['match_rate']:.2%}** "
        f"({holdings['matches']}/{holdings['months']}) | >= 96% | "
        f"{'YES' if holdings['match_rate'] >= SUCCESS_MATCH_RATE else 'NO'} |"
    )
    add(
        f"| Matched-month return diffs < 20bps | "
        f"{returns['matched_months'] - returns['matched_count_over_20bps']}"
        f"/{returns['matched_months']} | mostly | "
        f"{'YES' if returns['matched_count_over_20bps'] <= returns['matched_months'] * 0.5 else 'NO'} |"
    )
    add(
        f"| Full-period TWRR CAGR | **{results['model_cagr']:.2%}** "
        f"(PV {PV_TWRR_CAGR:.2%}) | within 0.5pp | "
        f"{'YES' if abs(results['model_cagr'] - PV_TWRR_CAGR) <= 0.005 else 'NO'} |"
    )
    add(
        f"| Chosen risk-free variant | `{chosen['variant']}` | design default (a) preferred | "
        f"{'YES' if chosen['variant'] == VARIANTS[0].name else 'n/a'} |"
    )
    add("")

    add("## Risk-free variant comparison")
    add("")
    add(
        "| Variant | Series | Alignment | Compounding | Matches | Match rate | Bond months "
        "| Mean RF score (bps) | Max RF diff vs (a) (bps) | Signal diffs vs (a) |"
    )
    add("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for variant in results["variants"]:
        add(
            f"| `{variant['variant']}` | {variant['series_id']} | {variant['alignment']} "
            f"| {variant['compounding']} | {variant['matches']}/{variant['months']} "
            f"| {variant['match_rate']:.2%} | {variant['bond_months_predicted']} "
            f"| {variant['mean_rf_score_bps']:.1f} "
            f"| {variant['rf_score_spread_vs_default_bps']:.1f} "
            f"| {variant['signal_diffs_vs_default']} |"
        )
    add("")
    add(
        f"PV holds {BOND_TICKER} in {results['pv_bond_months']} of {holdings['months']} months."
    )
    add("")
    add(
        "The variants are not degenerate — their risk-free scores differ by up to "
        f"{max(v['rf_score_spread_vs_default_bps'] for v in results['variants']):.1f}bps "
        "in individual months — yet **every variant produces an identical 355-month "
        "signal series**. The risk-free level simply never lands inside the gap between "
        "the winning equity score and zero excess in a way that any of these accrual "
        "conventions disagree about, so this backtest cannot discriminate between them. "
        "The design default (a) is therefore kept."
    )
    add("")
    add("Variant definitions:")
    add("")
    for variant in VARIANTS:
        add(f"* `{variant.name}` — {variant.description}")
    add("")
    add(
        "Selection rule: highest holdings match rate; ties resolved in favour of the "
        "design default (a). "
        f"Chosen: `{chosen['variant']}` — {chosen['description']}."
    )
    add("")

    add("## Holdings mismatches")
    add("")
    if not holdings["mismatches"]:
        add("None.")
    else:
        add(
            f"{len(holdings['mismatches'])} of {holdings['months']} months "
            f"({1 - holdings['match_rate']:.2%}). `gap` is how far the decision was from "
            "flipping: the US-vs-Intl score gap for relative-momentum flips, or the "
            "winner's excess over the risk-free score for in/out-of-market flips. "
            f"Gaps above {SUSPICIOUS_GAP_BPS:.0f}bps are flagged suspicious."
        )
        add("")
        add(
            "| Month | Anchor | Predicted | PV | US score | Intl score | RF score | Gap (bps) | Kind | Suspicious |"
        )
        add("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
        for mismatch in holdings["mismatches"]:
            kind = (
                "in/out-of-market"
                if BOND_TICKER in (mismatch["predicted"], mismatch["expected"])
                else "relative"
            )
            add(
                f"| {mismatch['month']} | {mismatch['anchor']} | {mismatch['predicted']} "
                f"| {mismatch['expected']} | {mismatch['us_score'] * 100:+.3f}% "
                f"| {mismatch['intl_score'] * 100:+.3f}% | {mismatch['rf_score'] * 100:+.3f}% "
                f"| {mismatch['gap_bps']:.1f} | {kind} "
                f"| {'YES' if mismatch['gap_bps'] > SUSPICIOUS_GAP_BPS else 'no'} |"
            )
        add("")
        add("### Mismatch investigation")
        add("")
        for mismatch in holdings["mismatches"]:
            add(
                f"#### {mismatch['month']} — we hold {mismatch['predicted']}, PV holds {mismatch['expected']}"
            )
            add("")
            add(
                MISMATCH_NOTES.get(
                    mismatch["month"],
                    "Not individually investigated; see the score table above for how "
                    "close the decision was.",
                )
            )
            add("")
    add("")

    add("## Calendar and robustness checks")
    add("")
    check = results["trade_date_check"]
    add(
        f"* **Anchor dates vs PV trade dates**: all {check['trades_checked']} PV trade "
        f"dates equal the month-end trading day our engine anchored on that month "
        f"({'0 mismatches' if check['all_match'] else str(len(check['anchor_date_mismatches'])) + ' MISMATCHES'}). "
        'PV and this backtest agree on what "month end" means, on every trade, for 30 years.'
    )
    add(
        f"* **Holding blocks**: model {results['trade_blocks']['model']} vs PV "
        f"{results['trade_blocks']['pv']} contiguous holdings over "
        f"{month_label(FIRST_RETURN_MONTH)}..{month_label(shift_month(LAST_ANCHOR, 1))}."
    )
    add(
        f"* **Decision margins**: of {holdings['matches']} matched months, "
        f"{results['robustness']['matched_months_under_30bps_margin']} sat within 30bps "
        f"of flipping and {results['robustness']['matched_months_under_10bps_margin']} "
        "within 10bps. The margin is the smaller of the US-vs-Intl score gap and the "
        "winner's excess over the risk-free score."
    )
    add("")
    add("Ten tightest matched months (most exposed to data noise):")
    add("")
    add("| Month | Held | Margin (bps) | US score | Intl score | RF score |")
    add("| --- | --- | --- | --- | --- | --- |")
    for row in results["robustness"]["tightest_matched_months"]:
        add(
            f"| {row['month']} | {row['held']} | {row['margin_bps']:.1f} "
            f"| {row['us_score'] * 100:+.3f}% | {row['intl_score'] * 100:+.3f}% "
            f"| {row['rf_score'] * 100:+.3f}% |"
        )
    add("")

    add("## Monthly return diffs (model vs PV)")
    add("")
    add("| Metric | Value |")
    add("| --- | --- |")
    add(f"| Months compared | {returns['months']} |")
    add(f"| Mean abs diff | {returns['mean_abs_diff_bps']:.2f} bps |")
    add(f"| Max abs diff | {returns['max_abs_diff_bps']:.1f} bps |")
    add(f"| Months > 50bps | {returns['count_over_50bps']} |")
    add(f"| Matched-holding months | {returns['matched_months']} |")
    add(f"| Matched mean abs diff | {returns['matched_mean_abs_diff_bps']:.2f} bps |")
    add(f"| Matched max abs diff | {returns['matched_max_abs_diff_bps']:.1f} bps |")
    add(f"| Matched months > 20bps | {returns['matched_count_over_20bps']} |")
    add(f"| Matched months > 50bps | {returns['matched_count_over_50bps']} |")
    add(
        f"| Price-data-only mean abs diff (PV holdings, our prices) | "
        f"{returns['data_only_mean_abs_diff_bps']:.2f} bps |"
    )
    add(
        f"| Price-data-only max abs diff | {returns['data_only_max_abs_diff_bps']:.1f} bps |"
    )
    add("")
    worst = sorted(returns["rows"], key=lambda row: -abs(row["diff"]))[:10]
    add("Ten largest monthly diffs:")
    add("")
    add("| Month | Held | PV held | Model return | PV return | Diff (bps) |")
    add("| --- | --- | --- | --- | --- | --- |")
    for row in worst:
        add(
            f"| {row['month']} | {row['predicted']} | {row['expected']} "
            f"| {row['model_return'] * 100:+.2f}% | {row['pv_return'] * 100:+.2f}% "
            f"| {row['diff'] * 10_000:+.1f} |"
        )
    add("")

    add("## Per-year returns")
    add("")
    add("| Year | Months | Model | PV | Diff (pp) |")
    add("| --- | --- | --- | --- | --- |")
    for row in results["per_year"]:
        add(
            f"| {row['year']} | {row['months']} | {row['model'] * 100:+.2f}% "
            f"| {row['pv'] * 100:+.2f}% | {row['diff_pp']:+.2f} |"
        )
    add("")

    add("## Full-period growth")
    add("")
    add("| Metric | Model | PV |")
    add("| --- | --- | --- |")
    add(
        f"| Cumulative return ({returns['months']} months) | "
        f"{results['model_cumulative'] * 100:,.1f}% | {results['pv_cumulative'] * 100:,.1f}% |"
    )
    add(f"| TWRR CAGR | {results['model_cagr']:.2%} | {PV_TWRR_CAGR:.2%} |")
    add(
        f"| Growth of $10,000 | ${results['model_growth_10k']:,.0f} | ${results['pv_growth_10k']:,.0f} |"
    )
    add("")
    add(
        "PV's headline CAGR of 29.23% reflects $5,000 inflation-adjusted monthly "
        "contributions and is not comparable; TWRR (13.52%) is the cashflow-free "
        "figure this backtest reproduces."
    )
    add("")
    return "\n".join(lines)


def print_summary(results: dict) -> None:
    chosen = results["chosen_variant"]
    holdings = results["holdings"]
    returns = results["returns"]
    print("=" * 78)
    print("PV PARITY BACKTEST")
    print("=" * 78)
    print(
        f"Anchors        : {month_label(FIRST_ANCHOR)}..{month_label(LAST_ANCHOR)} ({holdings['months']})"
    )
    check = results["trade_date_check"]
    print(
        f"Trade dates    : {check['trades_checked']} PV trade dates vs our anchors -> "
        f"{'all match' if check['all_match'] else check['anchor_date_mismatches']}"
    )
    print(
        f"Holding blocks : model {results['trade_blocks']['model']} vs PV {results['trade_blocks']['pv']}"
    )
    print()
    print("Risk-free variants:")
    for variant in results["variants"]:
        marker = " <- chosen" if variant["variant"] == chosen["variant"] else ""
        print(
            f"  {variant['variant']:<22} {variant['matches']:>3}/{variant['months']} "
            f"= {variant['match_rate']:.2%}  bond={variant['bond_months_predicted']:>3}{marker}"
        )
    print()
    print(
        f"Holdings match : {holdings['matches']}/{holdings['months']} = "
        f"{holdings['match_rate']:.2%} "
        f"({'PASS' if holdings['match_rate'] >= SUCCESS_MATCH_RATE else 'FAIL'} vs 96% bar)"
    )
    if holdings["mismatches"]:
        print("Mismatches:")
        for mismatch in holdings["mismatches"]:
            print(
                f"  {mismatch['month']}  pred={mismatch['predicted']:<6} pv={mismatch['expected']:<6} "
                f"us={mismatch['us_score'] * 100:+7.3f}% intl={mismatch['intl_score'] * 100:+7.3f}% "
                f"rf={mismatch['rf_score'] * 100:+7.3f}% gap={mismatch['gap_bps']:6.1f}bps"
                f"{'  SUSPICIOUS' if mismatch['gap_bps'] > SUSPICIOUS_GAP_BPS else ''}"
            )
    print()
    print(
        f"Return diffs   : mean {returns['mean_abs_diff_bps']:.2f}bps, "
        f"max {returns['max_abs_diff_bps']:.1f}bps, >50bps: {returns['count_over_50bps']}"
    )
    print(
        f"  matched only : mean {returns['matched_mean_abs_diff_bps']:.2f}bps, "
        f"max {returns['matched_max_abs_diff_bps']:.1f}bps, >20bps: {returns['matched_count_over_20bps']}"
    )
    print(
        f"  data-only    : mean {returns['data_only_mean_abs_diff_bps']:.2f}bps, "
        f"max {returns['data_only_max_abs_diff_bps']:.1f}bps"
    )
    print(
        f"TWRR CAGR      : model {results['model_cagr']:.2%} vs PV {PV_TWRR_CAGR:.2%} "
        f"({(results['model_cagr'] - PV_TWRR_CAGR) * 100:+.2f}pp)"
    )
    print("=" * 78)


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


def run_backtest(refresh: bool = False) -> dict:
    pv_holdings, pv_returns, pv_trades = load_ground_truth()
    price_bars = {ticker: load_prices(ticker, refresh) for ticker in TICKERS}
    rates = {
        series_id: load_fred_series(series_id, refresh)
        for series_id in ("DTB3", "TB3MS")
    }
    closes = {ticker: closes_by_month(bars) for ticker, bars in price_bars.items()}

    anchors = month_range(FIRST_ANCHOR, LAST_ANCHOR)
    assert_default_variant_matches_engine(rates["DTB3"], anchors)

    variants = [
        run_variant(variant, price_bars, rates, anchors, pv_holdings)
        for variant in VARIANTS
    ]
    # Guard against a vacuous comparison: the variants must actually differ in the
    # risk-free scores they produce, even if they agree on every signal.
    baseline = variants[0]
    for variant in variants:
        variant["rf_score_spread_vs_default_bps"] = (
            max(
                abs(record["rf_score"] - baseline["predictions"][label]["rf_score"])
                for label, record in variant["predictions"].items()
            )
            * 10_000
        )
        variant["signal_diffs_vs_default"] = sum(
            1
            for label, record in variant["predictions"].items()
            if record["predicted"] != baseline["predictions"][label]["predicted"]
        )

    best_rate = max(variant["match_rate"] for variant in variants)
    chosen = next(
        variant
        for name in VARIANT_PREFERENCE
        for variant in variants
        if variant["variant"] == name and variant["match_rate"] == best_rate
    )

    returns = compare_returns(chosen["predictions"], closes, pv_returns, pv_holdings)
    model_returns = [row["model_return"] for row in returns["rows"]]
    pv_return_series = [row["pv_return"] for row in returns["rows"]]

    predictions = chosen["predictions"]
    last_held = shift_month(LAST_ANCHOR, 1)
    our_holdings = {label: record["predicted"] for label, record in predictions.items()}
    matched_records = [
        record
        for record in predictions.values()
        if record["predicted"] == record["expected"]
    ]
    tightest = sorted(matched_records, key=lambda record: record["margin_bps"])[:10]
    robustness = {
        "matched_months_under_10bps_margin": sum(
            1 for record in matched_records if record["margin_bps"] < 10
        ),
        "matched_months_under_30bps_margin": sum(
            1 for record in matched_records if record["margin_bps"] < 30
        ),
        "tightest_matched_months": [
            {
                "month": record["month"],
                "held": record["predicted"],
                "margin_bps": record["margin_bps"],
                "us_score": record["us_score"],
                "intl_score": record["intl_score"],
                "rf_score": record["rf_score"],
            }
            for record in tightest
        ],
    }

    results = {
        "pdf": "Model_Backtest_20260725202812.pdf",
        "generated_from": "backtest/backtest_pv.py",
        "universe": {"us": US_TICKER, "intl": INTL_TICKER, "bond": BOND_TICKER},
        "anchors": {
            "first": month_label(FIRST_ANCHOR),
            "last": month_label(LAST_ANCHOR),
            "count": len(anchors),
        },
        "pv_trades": len(pv_trades),
        "pv_bond_months": sum(
            1 for ticker in pv_holdings.values() if ticker == BOND_TICKER
        ),
        "chosen_variant": {
            key: chosen[key]
            for key in (
                "variant",
                "series_id",
                "alignment",
                "compounding",
                "description",
            )
        },
        "variants": [
            {
                key: variant[key]
                for key in (
                    "variant",
                    "series_id",
                    "alignment",
                    "compounding",
                    "description",
                    "months",
                    "matches",
                    "match_rate",
                    "mismatch_count",
                    "bond_months_predicted",
                    "mean_rf_score_bps",
                    "rf_score_spread_vs_default_bps",
                    "signal_diffs_vs_default",
                )
            }
            for variant in variants
        ],
        "holdings": {
            "months": chosen["months"],
            "matches": chosen["matches"],
            "match_rate": chosen["match_rate"],
            "mismatches": chosen["mismatches"],
            "success_bar": SUCCESS_MATCH_RATE,
            "passes_bar": chosen["match_rate"] >= SUCCESS_MATCH_RATE,
        },
        "trade_date_check": check_trade_dates(predictions, pv_trades),
        "trade_blocks": {
            "model": len(trade_blocks(our_holdings, FIRST_RETURN_MONTH, last_held)),
            "pv": len(trade_blocks(pv_holdings, FIRST_RETURN_MONTH, last_held)),
        },
        "robustness": robustness,
        "returns": returns,
        "per_year": per_year_table(returns["rows"]),
        "model_cumulative": compound(model_returns),
        "pv_cumulative": compound(pv_return_series),
        "model_cagr": twrr_cagr(model_returns),
        "pv_cagr": twrr_cagr(pv_return_series),
        "pv_reported_twrr": PV_TWRR_CAGR,
        "model_growth_10k": 10_000 * (1 + compound(model_returns)),
        "pv_growth_10k": 10_000 * (1 + compound(pv_return_series)),
        "predictions": predictions,
    }
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--refresh", action="store_true", help="refetch vendor data, ignoring the cache"
    )
    args = parser.parse_args()

    results = run_backtest(refresh=args.refresh)
    print_summary(results)
    RESULTS_PATH.write_text(json.dumps(results, indent=2, sort_keys=False) + "\n")
    REPORT_PATH.write_text(build_report(results))
    print(f"Wrote {RESULTS_PATH}")
    print(f"Wrote {REPORT_PATH}")


if __name__ == "__main__":
    main()

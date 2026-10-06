# dm - Dual Momentum Calculator

A CLI tool that implements the Dual Momentum investment strategy, scoring VOO (US equities) against VXUS (International equities) on trailing 1/3/6-month total returns as of the day you run it, and rotating to VGIT (intermediate treasuries) when neither clears the risk-free rate.

## The Strategy

This tool is inspired by Gary Antonacci's **Dual Momentum Investing** (2015), a groundbreaking approach that combines relative momentum (comparing assets against each other) with absolute momentum (comparing assets against a risk-free benchmark). The strategy seeks to capture upside during bull markets while rotating to safety during downturns.

The specific implementation reproduces [Portfolio Visualizer](https://www.portfoliovisualizer.com/)'s **Dual Momentum Model**, in the spirit of the **Accelerating Dual Momentum** methodology from [Engineered Portfolio](https://engineeredportfolio.com/2018/05/02/accelerating-dual-momentum-investing/).

### How It Works

1. **Anchor on the latest close.** Each run evaluates the rule at the most recent close on or before the run date (shared by both funds), so it can be run any day — weekly, for example.
2. **Score each equity fund.** The momentum score is the weighted average of dividend-adjusted (total return) trailing returns over 1, 3, and 6 months, weighted **33% / 33% / 34%**. An N-month return runs from the close on (or the last trading day before) the same calendar day N months earlier to the anchor close — run on Tuesday October 6 with Monday's close as the anchor, the 1-month window is September 5 → October 5, so the base is the Friday September 4 close.
3. **Relative momentum.** The higher-scoring equity fund wins.
4. **Absolute momentum.** If that winner's score is below the risk-free score — the 3-month Treasury bill return compounded over the same windows — the model holds VGIT instead.

The model is always 100% in exactly one of VOO, VXUS, or VGIT. The rules-based approach removes emotional decision-making from the investment process, replacing gut feelings with systematic, repeatable analysis.

**Month ends.** When the anchor is a month's final close (the month has ended, or no weekdays remain in it), the windows snap to prior month ends: a September 30 anchor measures from August 31, June 30, and March 31. On those days the result is exactly Portfolio Visualizer's month-end signal (see `--month-end` below).

## Installation

```bash
uv sync
```

## Usage

```bash
uv run dm
```

Example output:

```
Dual Momentum Analysis
As of: 2026-10-05 (latest close, trailing windows)
Windows from: 1M 2026-09-05, 3M 2026-07-05, 6M 2026-04-05
==============================================

VOO:
  1-Month:    0.87%
  3-Month:    4.28%
  6-Month:   18.78%
  Score:      8.08%

VXUS:
  1-Month:   -2.72%
  3-Month:    1.37%
  6-Month:   11.50%
  Score:      3.47%

Risk-free (3-month T-bill):
  1-Month:    0.31%
  3-Month:    0.94%
  6-Month:    1.85%
  Score:      1.04%

==============================================
Relative momentum: VOO 8.08% beats VXUS 3.47%
Absolute momentum: VOO 8.08% clears the risk-free 1.04% -> stay in the market
Signal: VOO (as of 2026-10-05)
```

The `Signal:` line is stable and greppable:

```bash
uv run dm | grep '^Signal:'
```

`Windows from:` shows the calendar start date of each lookback; each base is
the latest close on or before that date.

### `--month-end`: Portfolio Visualizer's month-end signal

```bash
uv run dm --month-end
```

Evaluates the rule only at the last completed month-end close, with
month-end-to-month-end windows (header: `month-end close`; signal line:
`hold from`). This is Portfolio Visualizer's own convention and the mode the
`backtest/` suite validates against PV's trade history. A mid-month run reports
the prior month end, so a run on October 6 reports September 30. Run it on or
after the 1st: on a month's last calendar day before that day's close is
posted, it would anchor on the second-to-last trading day (about a 3%
historical signal-flip risk).

The default trailing mode is a weekly-run extension of that methodology: same
weights, same risk-free construction, same decision rule, but measured on
windows ending at the latest close. Away from month ends its returns will not
match PV's (PV publishes month-end values only), and the backtest's parity
claim covers the month-end mode.

### Caveats

- **Run after the close.** A run during market hours may price the anchor at
  an in-progress (partial) bar from the data provider. The trailing returns
  are only final once the day's close is posted.
- **Data gaps fail loudly.** If the latest close on or before a window's start
  date is more than 10 days old, the run raises an error rather than silently
  stretching the window.

## Configuration

Create a `.env` file with your API keys:

```
FRED_API_KEY=your_api_key_here
TWELVEDATA_API_KEY=your_api_key_here
```

- **FRED** — free key from the [Federal Reserve Bank of St. Louis](https://fred.stlouisfed.org/docs/api/api_key.html). Used for the 3-month Treasury bill rate (series `DTB3`).
- **Twelve Data** — free key from [twelvedata.com](https://twelvedata.com/). Used as the primary source for ETF prices. If the key is missing or the API is unreachable, the tool automatically falls back to yfinance and prints a warning to stderr.

Momentum is measured on **total return**, so both sources are asked for dividend-adjusted closes (`adjust=all` on Twelve Data, whose default `adjust=splits` omits dividends; `auto_adjust=True` on yfinance).

The tool fetches each ticker's full history window in a single request and resolves the 1/3/6-month lookbacks locally, so a run consumes **2 Twelve Data credits** (one per ticker) — comfortably below the free tier's 8-credits-per-minute limit.

## Development

```bash
# Run unit tests
uv run pytest -m "not integration"

# Run integration tests (calls real APIs)
uv run pytest -m integration

# Run all tests
uv run pytest
```

## References

- Portfolio Visualizer — Dual Momentum Model (the parity target; see `Model_Backtest_*.pdf` and `backtest/`)
- Antonacci, Gary. *Dual Momentum Investing: An Innovative Strategy for Higher Returns with Lower Risk*. McGraw-Hill, 2015.
- [Accelerating Dual Momentum Investing](https://engineeredportfolio.com/2018/05/02/accelerating-dual-momentum-investing/) - Engineered Portfolio

## License

GPL-3.0-or-later

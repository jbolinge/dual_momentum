# dm - Dual Momentum Calculator

A CLI tool that implements the Dual Momentum investment strategy, scoring VOO (US equities) against VXUS (International equities) at each month-end close and rotating to VGIT (intermediate treasuries) when neither clears the risk-free rate.

## The Strategy

This tool is inspired by Gary Antonacci's **Dual Momentum Investing** (2015), a groundbreaking approach that combines relative momentum (comparing assets against each other) with absolute momentum (comparing assets against a risk-free benchmark). The strategy seeks to capture upside during bull markets while rotating to safety during downturns.

The specific implementation reproduces [Portfolio Visualizer](https://www.portfoliovisualizer.com/)'s **Dual Momentum Model**, in the spirit of the **Accelerating Dual Momentum** methodology from [Engineered Portfolio](https://engineeredportfolio.com/2018/05/02/accelerating-dual-momentum-investing/).

### How It Works

1. **Anchor on the last completed month end.** Signals are computed at month-end closes and held for the following month, so a mid-July run reports the June 30 signal.
2. **Score each equity fund.** The momentum score is the weighted average of dividend-adjusted (total return) month-end-to-month-end returns over 1, 3, and 6 months, weighted **33% / 33% / 34%**.
3. **Relative momentum.** The higher-scoring equity fund wins.
4. **Absolute momentum.** If that winner's score is below the risk-free score — the 3-month Treasury bill return compounded over the same windows — the model holds VGIT instead.

The model is always 100% in exactly one of VOO, VXUS, or VGIT. The rules-based approach removes emotional decision-making from the investment process, replacing gut feelings with systematic, repeatable analysis.

> **When to run**: run `dm` on or after the 1st of the month to get the prior month's final signal. Running *on* the last calendar day of a month before that day's close is posted would silently anchor on the second-to-last trading day — over the 1997-2026 backtest, that one-day-early anchor would have flipped the signal in about 3% of months.

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
As of: 2026-06-30 (month-end close)
==============================================

VOO:
  1-Month:   -0.96%
  3-Month:   15.27%
  6-Month:   10.18%
  Score:      8.18%

VXUS:
  1-Month:   -0.22%
  3-Month:   11.36%
  6-Month:   13.95%
  Score:      8.42%

Risk-free (3-month T-bill):
  1-Month:    0.30%
  3-Month:    0.90%
  6-Month:    1.81%
  Score:      1.01%

==============================================
Relative momentum: VXUS 8.42% beats VOO 8.18%
Absolute momentum: VXUS 8.42% clears the risk-free 1.01% -> stay in the market
Signal: VXUS (hold from 2026-06-30)
```

The `Signal:` line is stable and greppable:

```bash
uv run dm | grep '^Signal:'
```

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

# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

`dm` is a CLI application built on Portfolio Visualizer's Dual Momentum Model for the user's live tickers. Each run scores VOO (US) and VXUS (International) on the weighted average of their trailing 1, 3, and 6 month total returns as of the latest close, compares the winner against the 3-month Treasury bill return over the same windows, and prints the single ticker to hold — VOO, VXUS, or VGIT (intermediate treasuries) when equity momentum is below the risk-free rate. The user runs it weekly and shifts 25% of the portfolio toward the signal each week, so the default mode must reflect the run date, not the last month end.

## Commands

```bash
# Install dependencies
uv sync

# Run the CLI
uv run dm

# PV's month-end signal (last completed month end, month-end-to-month-end windows)
uv run dm --month-end

# Run unit tests only (fast, no external API calls)
uv run pytest -m "not integration"

# Run integration tests only (calls real APIs)
uv run pytest -m integration

# Run all tests
uv run pytest

# Run a single test
uv run pytest tests/test_file.py::test_function_name -v
```

## Architecture

```
src/dm/
├── cli.py          # Entry point, fetch orchestration, output formatting
├── data.py         # Data fetching (TwelveData primary, yfinance fallback, FRED)
└── signals.py      # Pure signal engine: trailing/month-end windows, scores, decision rule
tests/
└── ...             # Mirror structure of src/dm/
```

### Data Flow

1. `cli.py` fetches ~8 months of daily closes for VOO and VXUS (one request each) plus the DTB3 rate series, then hands them to the signal engine (`compute_signal_trailing` by default, `compute_signal` with `--month-end`)
2. `data.py` fetches dividend-adjusted closes from TwelveData (`adjust=all`), falling back to yfinance (`auto_adjust=True`), and the 3-month T-bill series from FRED (DTB3)
3. `signals.py` anchors on the latest shared close (or, with `--month-end`, the latest completed month end), computes 1/3/6-month total returns, weights them 33/33/34, and applies the dual-momentum rule

### Key Design Decisions

- **PV parity**: The methodology mirrors Portfolio Visualizer's Dual Momentum Model as documented in `Model_Backtest_20260725202812.pdf`; `backtest/` validates the month-end engine (`compute_signal` + `accumulate_rf_returns`) against PV's own trade history. Parity is defined on month ends only
- **Trailing windows (default)**: Anchor = the earlier of the two series' latest closes on or before today. An N-month window starts on the same calendar day N months before the anchor (`relativedelta`, clamped to shorter months); its base is the latest close on or before that date, and a base more than 10 days stale raises instead of stretching the window. Mid-month results will not match PV's published numbers — that is expected
- **Month-end snapping**: When the anchor is its month's final close (`is_month_end_anchor`: the month has ended by `today`, or no weekdays remain after the anchor), window starts snap to prior months' last calendar days (Sep 30 → Aug 31, not Aug 30). This makes the trailing engine reproduce `compute_signal` exactly on month-end closes; a test enforces it
- **`--month-end` mode**: Signals evaluated only at end-of-month closes and held the following month. Month M becomes eligible once its last calendar day arrives, so a mid-July run anchors on June 30. Running on a month's last calendar day before the close is posted would anchor on the second-to-last trading day (~3% historical signal-flip risk)
- **Total return required**: Momentum is computed on dividend-adjusted closes. TwelveData defaults to `adjust=splits`, which understates 6-month returns by tens of basis points, so `adjust=all` is mandatory
- **Weighting**: 1, 3, and 6 month lookbacks weighted 33% / 33% / 34% (PV's weights), not equal thirds
- **Risk-free rate**: FRED DTB3 (3-month T-bill). The window is split into one-month steps matching the equity windows; each step earns the annual rate observed on or before the step's start date divided by 12, and window returns compound the steps (`trailing_rf_returns`). At month ends this is PV's convention: month m earns the rate observed at the end of month m-1
- **Decision rule**: Relative momentum picks the higher-scoring equity fund; absolute momentum swaps into VGIT only when that winner's score is strictly below the risk-free score
- **Tiebreakers**: Equal equity scores prefer VOO; a winner tied with the risk-free score stays in equities
- **Missing data handling**: If no observation exists for a target date, use the most recent data prior to that date
- **Intraday runs**: A run during market hours may price the anchor at the provider's in-progress bar; returns are final only after the close is posted

## Environment

Requires `.env` file with:
```
FRED_API_KEY=your_api_key_here
TWELVEDATA_API_KEY=your_api_key_here
```

## Development Approach

This project follows test-driven development (TDD). Write tests first, expect them to fail, then implement code to pass tests.

# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

`dm` is a CLI application that reproduces Portfolio Visualizer's Dual Momentum Model for the user's live tickers. At each month-end close it scores VOO (US) and VXUS (International) on the weighted average of their 1, 3, and 6 month total returns, compares the winner against the 3-month Treasury bill return, and prints the single ticker to hold for the coming month — VOO, VXUS, or VGIT (intermediate treasuries) when equity momentum is below the risk-free rate.

## Commands

```bash
# Install dependencies
uv sync

# Run the CLI
uv run dm

# Preview the signal at the latest close instead of the last month end
uv run dm --now

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
└── signals.py      # Pure signal engine: month-end anchoring, scores, decision rule
tests/
└── ...             # Mirror structure of src/dm/
```

### Data Flow

1. `cli.py` fetches ~8 months of daily closes for VOO and VXUS (one request each) plus the DTB3 rate series, then hands them to the signal engine
2. `data.py` fetches dividend-adjusted closes from TwelveData (`adjust=all`), falling back to yfinance (`auto_adjust=True`), and the 3-month T-bill series from FRED (DTB3)
3. `signals.py` reduces daily bars to month-end closes, anchors on the latest completed month, computes 1/3/6-month total returns, weights them 33/33/34, and applies the dual-momentum rule

### Key Design Decisions

- **PV parity**: The methodology mirrors Portfolio Visualizer's Dual Momentum Model as documented in `Model_Backtest_20260725202812.pdf`; `backtest/` validates the engine against PV's own trade history
- **Month-end anchoring**: Signals are evaluated only at end-of-month closes and held the following month. Month M becomes eligible once its last calendar day arrives, so a mid-July run anchors on June 30. Run `dm` on or after the 1st of the month — running on a month's last calendar day before the close is posted would anchor on the second-to-last trading day (~3% historical signal-flip risk)
- **Total return required**: Momentum is computed on dividend-adjusted closes. TwelveData defaults to `adjust=splits`, which understates 6-month returns by tens of basis points, so `adjust=all` is mandatory
- **Weighting**: 1, 3, and 6 month lookbacks weighted 33% / 33% / 34% (PV's weights), not equal thirds
- **Risk-free rate**: FRED DTB3 (3-month T-bill). The return earned in month m uses the annual rate observed at the end of month m-1 divided by 12; window returns compound those monthly returns
- **Decision rule**: Relative momentum picks the higher-scoring equity fund; absolute momentum swaps into VGIT only when that winner's score is strictly below the risk-free score
- **Tiebreakers**: Equal equity scores prefer VOO; a winner tied with the risk-free score stays in equities
- **Missing data handling**: If no observation exists for a target date, use the most recent data prior to that date
- **`--now` preview mode**: Anchors on the latest close on or before today (shared between both equity series) instead of the last completed month end. Lookbacks run from the close on or before the date exactly 1/3/6 calendar months before the anchor, and the risk-free windows use the rates observed at those same date-shifted anchors. This is an intra-month preview; PV parity (and the backtest) is defined only on the default month-end mode

## Environment

Requires `.env` file with:
```
FRED_API_KEY=your_api_key_here
TWELVEDATA_API_KEY=your_api_key_here
```

## Development Approach

This project follows test-driven development (TDD). Write tests first, expect them to fail, then implement code to pass tests.

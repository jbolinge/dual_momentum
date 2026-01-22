# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

`dm` is a CLI application that implements a dual momentum strategy comparison. It calculates simple returns for VOO (US) and VXUS (International) ETFs over 1, 3, and 6 month periods, compares them against 30-day treasury returns, and recommends the instrument with the highest equally-weighted average return.

## Commands

```bash
# Install dependencies
uv sync

# Run the CLI
uv run dm

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
├── cli.py          # Entry point, output formatting
├── data.py         # Data fetching (yfinance, FRED API)
├── returns.py      # Return calculations
└── compare.py      # Comparison logic and winner determination
tests/
└── ...             # Mirror structure of src/dm/
```

### Data Flow

1. `cli.py` orchestrates the workflow
2. `data.py` fetches prices from yfinance (VOO, VXUS) and treasury rates from FRED (DGS1MO)
3. `returns.py` calculates simple returns for each period, converting annualized treasury rate to period-equivalent returns
4. `compare.py` computes weighted averages and determines the winner (1-month return breaks ties)

### Key Design Decisions

- **Missing data handling**: If no data exists for a target date, use the most recent data prior to that date
- **Treasury rate conversion**: Annualized rate converted to period returns (rate/12 for 1 month, rate/4 for 3 months, rate/2 for 6 months)
- **Equal weighting**: All three time periods (1, 3, 6 months) weighted equally (1/3 each)
- **Tiebreaker**: If weighted returns are equal, 1-month return determines winner; if still equal, both are displayed

## Environment

Requires `.env` file with:
```
FRED_API_KEY=your_api_key_here
```

## Development Approach

This project follows test-driven development (TDD). Write tests first, expect them to fail, then implement code to pass tests.

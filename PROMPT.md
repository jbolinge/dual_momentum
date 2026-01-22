# Dual Momentum CLI Development Prompt

You are developing `dm`, a Python CLI application following test-driven development (TDD) and the UNIX philosophy of doing one thing well.

## Your Task

Implement a CLI that compares weighted returns of VOO/VXUS against 30-day treasury rates.

## Requirements

### Data Sources
- **VOO and VXUS prices**: Use `yfinance` library
- **30-day treasury rate**: Use FRED API with series `DGS1MO` (load API key from `.env` file using `python-dotenv`)

### Calculations
1. Calculate simple return for VOO, VXUS over 1, 3, and 6 month periods from today
2. For treasury: convert annualized DGS1MO rate to period-equivalent returns:
   - 1-month return = rate / 12
   - 3-month return = rate / 4
   - 6-month return = rate / 2
3. Calculate equally-weighted average return for each instrument (1/3 weight per period)
4. If no data exists for a target date, use the most recent data prior to that date

### Output (plain text)
Display:
- Individual period returns for VOO, VXUS, and Treasury
- Weighted average return for each instrument
- The winner (highest weighted return)
- Tiebreaker: use 1-month return if weighted averages are equal; if still equal, show both

### Technical Stack
- Python 3.12+
- `uv` for package management (use `uv run`, `uv add`, NOT `uv pip`)
- `pytest` for testing
- Source code in `src/dm/`, tests in `tests/`

## TDD Workflow

1. Check existing tests with `uv run pytest -v`
2. If tests fail, implement code to make them pass
3. If all tests pass, check if functionality is complete
4. Write new tests for any missing functionality
5. Implement code to pass new tests
6. Repeat until complete

## Architecture

```
src/dm/
├── __init__.py
├── cli.py          # Entry point, output formatting
├── data.py         # Data fetching (yfinance, FRED)
├── returns.py      # Return calculations
└── compare.py      # Comparison logic
tests/
├── __init__.py
├── test_data.py
├── test_returns.py
├── test_compare.py
└── test_cli.py
```

## Completion Criteria

The application is complete when:
1. All tests pass (`uv run pytest` returns 0 exit code)
2. Running `uv run dm` produces correct output showing:
   - Period returns for all instruments
   - Weighted returns for all instruments
   - The recommended instrument (winner)

When complete, output: `<promise>TASK COMPLETE</promise>`

## Important Notes

- Read CLAUDE.md for project context
- Keep code simple and focused - UNIX philosophy
- Mock external API calls in tests
- Do not hardcode API keys
- Use Context7 MCP for up-to-date library documentation when needed

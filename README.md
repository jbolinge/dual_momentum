# dm - Dual Momentum Calculator

A CLI tool that implements the Dual Momentum investment strategy, comparing weighted returns of VOO (US equities) and VXUS (International equities) against treasury rates to identify the optimal investment allocation.

## The Strategy

This tool is inspired by Gary Antonacci's **Dual Momentum Investing** (2015), a groundbreaking approach that combines relative momentum (comparing assets against each other) with absolute momentum (comparing assets against a risk-free benchmark). The strategy seeks to capture upside during bull markets while rotating to safety during downturns.

The specific implementation follows the **Accelerating Dual Momentum** methodology outlined at [Engineered Portfolio](https://engineeredportfolio.com/2018/05/02/accelerating-dual-momentum-investing/), which calculates momentum by equally weighting 1-month, 3-month, and 6-month returns.

### How It Works

1. **Calculate momentum scores** for VOO and VXUS by averaging their 1, 3, and 6-month returns
2. **Compare against treasuries** to determine if equity momentum is positive
3. **Select the winner**: The instrument with the highest weighted return is recommended

The rules-based approach removes emotional decision-making from the investment process, replacing gut feelings with systematic, repeatable analysis.

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
========================================

VOO:
  1-Month:     0.78%
  3-Month:     3.66%
  6-Month:    10.43%
  Weighted:    4.95%

VXUS:
  1-Month:     5.27%
  3-Month:     8.38%
  6-Month:    15.87%
  Weighted:    9.84%

Treasury:
  1-Month:     0.31%
  3-Month:     0.94%
  6-Month:     1.88%
  Weighted:    1.04%

========================================
Winner: VXUS
```

## Configuration

Create a `.env` file with your FRED API key:

```
FRED_API_KEY=your_api_key_here
```

You can obtain a free API key from the [Federal Reserve Bank of St. Louis](https://fred.stlouisfed.org/docs/api/api_key.html).

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

- Antonacci, Gary. *Dual Momentum Investing: An Innovative Strategy for Higher Returns with Lower Risk*. McGraw-Hill, 2015.
- [Accelerating Dual Momentum Investing](https://engineeredportfolio.com/2018/05/02/accelerating-dual-momentum-investing/) - Engineered Portfolio

## License

GPL-3.0-or-later

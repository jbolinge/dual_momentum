# dm - Dual Momentum Calculator

A CLI tool that compares weighted returns of VOO/VXUS ETFs against 30-day treasury rates to recommend the best instrument.

## Installation

```bash
uv sync
```

## Usage

```bash
uv run dm
```

## Configuration

Create a `.env` file with your FRED API key:

```
FRED_API_KEY=your_api_key_here
```

## Development

```bash
# Run tests
uv run pytest

# Run single test
uv run pytest tests/test_file.py::test_name -v
```

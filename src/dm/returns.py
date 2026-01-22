"""Return calculations."""


def calculate_simple_return(start_price: float, end_price: float) -> float:
    """Calculate simple return between two prices.

    Args:
        start_price: Starting price
        end_price: Ending price

    Returns:
        Simple return as a decimal (e.g., 0.10 for 10%)
    """
    return (end_price - start_price) / start_price


def convert_treasury_rate(annual_rate: float, months: int) -> float:
    """Convert annualized treasury rate to period-equivalent return.

    Args:
        annual_rate: Annualized rate as decimal (e.g., 0.05 for 5%)
        months: Number of months for the period

    Returns:
        Period-equivalent return
    """
    return annual_rate * months / 12


def calculate_weighted_return(returns: list[float]) -> float:
    """Calculate equally-weighted average return.

    Args:
        returns: List of returns for each period

    Returns:
        Weighted average return
    """
    return sum(returns) / len(returns)

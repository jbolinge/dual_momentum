"""Comparison logic and winner determination."""

from dataclasses import dataclass


@dataclass
class InstrumentReturns:
    """Container for an instrument's returns across periods."""

    name: str
    returns_1m: float
    returns_3m: float
    returns_6m: float
    weighted_return: float


def determine_winner(
    voo: InstrumentReturns,
    vxus: InstrumentReturns,
    treasury: InstrumentReturns,
) -> list[InstrumentReturns]:
    """Determine the winning instrument(s) based on weighted returns.

    Args:
        voo: VOO returns
        vxus: VXUS returns
        treasury: Treasury returns

    Returns:
        List of winning instrument(s). Usually one, but can be multiple if tied.
        Tiebreaker: 1-month return. If still tied, return all tied instruments.
    """
    instruments = [voo, vxus, treasury]

    # Find max weighted return
    max_weighted = max(i.weighted_return for i in instruments)

    # Get all instruments with max weighted return
    top_instruments = [i for i in instruments if i.weighted_return == max_weighted]

    if len(top_instruments) == 1:
        return top_instruments

    # Tiebreaker: use 1-month return
    max_1m = max(i.returns_1m for i in top_instruments)
    winners = [i for i in top_instruments if i.returns_1m == max_1m]

    return winners

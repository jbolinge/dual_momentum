"""Tests for comparison logic."""

import pytest

from dm.compare import determine_winner, InstrumentReturns


class TestDetermineWinner:
    """Tests for determining the winning instrument."""

    def test_voo_wins_higher_weighted(self):
        """Test VOO wins with higher weighted return."""
        voo = InstrumentReturns(
            name="VOO",
            returns_1m=0.05,
            returns_3m=0.08,
            returns_6m=0.12,
            weighted_return=0.0833,
        )
        vxus = InstrumentReturns(
            name="VXUS",
            returns_1m=0.03,
            returns_3m=0.05,
            returns_6m=0.07,
            weighted_return=0.05,
        )
        treasury = InstrumentReturns(
            name="Treasury",
            returns_1m=0.004,
            returns_3m=0.012,
            returns_6m=0.024,
            weighted_return=0.0133,
        )

        winners = determine_winner(voo, vxus, treasury)

        assert len(winners) == 1
        assert winners[0].name == "VOO"

    def test_treasury_wins_higher_weighted(self):
        """Test Treasury wins with higher weighted return."""
        voo = InstrumentReturns(
            name="VOO",
            returns_1m=-0.05,
            returns_3m=-0.08,
            returns_6m=-0.12,
            weighted_return=-0.0833,
        )
        vxus = InstrumentReturns(
            name="VXUS",
            returns_1m=-0.03,
            returns_3m=-0.05,
            returns_6m=-0.07,
            weighted_return=-0.05,
        )
        treasury = InstrumentReturns(
            name="Treasury",
            returns_1m=0.004,
            returns_3m=0.012,
            returns_6m=0.024,
            weighted_return=0.0133,
        )

        winners = determine_winner(voo, vxus, treasury)

        assert len(winners) == 1
        assert winners[0].name == "Treasury"

    def test_tiebreaker_uses_1m_return(self):
        """Test tiebreaker uses 1-month return when weighted are equal."""
        voo = InstrumentReturns(
            name="VOO",
            returns_1m=0.06,  # Higher 1-month
            returns_3m=0.04,
            returns_6m=0.05,
            weighted_return=0.05,  # Same weighted
        )
        vxus = InstrumentReturns(
            name="VXUS",
            returns_1m=0.03,  # Lower 1-month
            returns_3m=0.06,
            returns_6m=0.06,
            weighted_return=0.05,  # Same weighted
        )
        treasury = InstrumentReturns(
            name="Treasury",
            returns_1m=0.004,
            returns_3m=0.012,
            returns_6m=0.024,
            weighted_return=0.0133,
        )

        winners = determine_winner(voo, vxus, treasury)

        assert len(winners) == 1
        assert winners[0].name == "VOO"

    def test_both_winners_when_fully_tied(self):
        """Test both shown when weighted and 1-month are equal."""
        voo = InstrumentReturns(
            name="VOO",
            returns_1m=0.05,
            returns_3m=0.05,
            returns_6m=0.05,
            weighted_return=0.05,
        )
        vxus = InstrumentReturns(
            name="VXUS",
            returns_1m=0.05,
            returns_3m=0.05,
            returns_6m=0.05,
            weighted_return=0.05,
        )
        treasury = InstrumentReturns(
            name="Treasury",
            returns_1m=0.004,
            returns_3m=0.012,
            returns_6m=0.024,
            weighted_return=0.0133,
        )

        winners = determine_winner(voo, vxus, treasury)

        assert len(winners) == 2
        names = [w.name for w in winners]
        assert "VOO" in names
        assert "VXUS" in names

    def test_three_way_tie_returns_all(self):
        """Test all three returned when fully tied."""
        voo = InstrumentReturns(
            name="VOO",
            returns_1m=0.05,
            returns_3m=0.05,
            returns_6m=0.05,
            weighted_return=0.05,
        )
        vxus = InstrumentReturns(
            name="VXUS",
            returns_1m=0.05,
            returns_3m=0.05,
            returns_6m=0.05,
            weighted_return=0.05,
        )
        treasury = InstrumentReturns(
            name="Treasury",
            returns_1m=0.05,
            returns_3m=0.05,
            returns_6m=0.05,
            weighted_return=0.05,
        )

        winners = determine_winner(voo, vxus, treasury)

        assert len(winners) == 3

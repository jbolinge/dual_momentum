"""Shared pytest fixtures."""

import pytest

from dm import data


@pytest.fixture(autouse=True)
def _reset_twelvedata_fallback_latch():
    """Ensure each test starts with a fresh TwelveData-fallback-warning latch."""
    data._reset_fallback_warning()
    yield
    data._reset_fallback_warning()

"""Test fixtures. Expanded in later phases."""

import pytest


@pytest.fixture
def hello():
    return "world"

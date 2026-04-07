"""\
Shared test fixtures for the GoFigr test suite.
"""
import pytest

from gofigr import GoFigr


@pytest.fixture
def mock_gf():
    """A GoFigr client that skips authentication.

    Provides access to all bound model classes (FileData, ImageData, etc.)
    without requiring server credentials or network access.
    """
    return GoFigr(url="http://localhost", authenticate=False)

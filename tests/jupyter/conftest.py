"""\
Shared pytest fixtures for Jupyter extension tests.

Copyright (c) 2026, Flagstaff Solutions, LLC
All rights reserved.

"""
import os
from pathlib import Path

import pytest

from tests.jupyter.harness import JupyterHarness

DATA_DIR = Path(__file__).parent.parent / "data"
BLOB_PATH = str(DATA_DIR / "blob.bin")


def configure_cell(analysis_expr="NotebookName()", auto_publish=False):
    """Returns the code for a configure() cell.

    Reads credentials via os.environ references so special characters
    in passwords are not mangled by string interpolation.
    """
    return (
        f"import os; configure("
        f"username=os.environ['GF_TEST_USER'], "
        f"password=os.environ['GF_TEST_PASSWORD'], "
        f"api_key=None, "
        f"workspace=None, "
        f"url=os.environ['GF_TEST_API_URL'], "
        f"analysis={analysis_expr}, "
        f"auto_publish={auto_publish})"
    )


def load_and_configure(harness, analysis_expr="NotebookName()", auto_publish=False):
    """Loads the extension and configures it. Raises AssertionError on failure."""
    result = harness.run_cell("%load_ext gofigr")
    assert not result.error_in_exec, f"load_ext failed: {result.error_in_exec}"

    result = harness.run_cell(configure_cell(analysis_expr, auto_publish=auto_publish))
    assert not result.error_in_exec, f"configure failed: {result.error_in_exec}"


@pytest.fixture
def harness(request):
    """Provides a started JupyterHarness, torn down after the test.

    The notebook name defaults to the test function name but can be overridden
    via ``@pytest.mark.parametrize`` or by passing ``notebook_name`` as an
    indirect parameter.
    """
    notebook_name = getattr(request, "param", None) or f"{request.node.name}.ipynb"
    h = JupyterHarness(notebook_name=notebook_name)
    h.start()
    yield h
    h.stop()

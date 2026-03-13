"""\
Centralized compatibility shims for optional and hard dependencies.

All symbols are re-exported for use by other modules.

Copyright (c) 2025, Flagstaff Solutions, LLC
All rights reserved.

"""
# pylint: disable=unused-import

import importlib.resources

# ---------------------------------------------------------------------------
# Section 1 — IPython (hard dependency, defensive guards)
# ---------------------------------------------------------------------------
try:
    from IPython import get_ipython
except ImportError:
    get_ipython = None

try:
    from IPython.core.display_functions import display as ipython_display
except (ModuleNotFoundError, ImportError):
    try:
        from IPython.core.display import display as ipython_display
    except (ModuleNotFoundError, ImportError):
        ipython_display = None

try:
    from IPython.core.display import HTML
except ImportError:
    HTML = None

try:
    from IPython.core.display import Javascript
except ImportError:
    Javascript = None

# ---------------------------------------------------------------------------
# Section 2 — Optional dependencies
# ---------------------------------------------------------------------------
PY3DMOL_AVAILABLE = False
try:
    import py3Dmol
    PY3DMOL_AVAILABLE = True
except ImportError:
    py3Dmol = None

PLOTNINE_AVAILABLE = False
try:
    import plotnine
    PLOTNINE_AVAILABLE = True
except ImportError:
    pass

try:
    from html2image import Html2Image
except ImportError:
    Html2Image = None

try:
    from databricks.sdk import WorkspaceClient
except ImportError:
    WorkspaceClient = None

# ---------------------------------------------------------------------------
# Section 3 — Hard deps with defensive guards
# ---------------------------------------------------------------------------
try:
    import git as gitpython
except ImportError:
    gitpython = None

try:
    import nest_asyncio
except ImportError:
    nest_asyncio = None

try:
    from ipywidgets import widgets as ipywidgets_widgets
    from ipywidgets.comm import create_comm
except ImportError:
    ipywidgets_widgets = None
    create_comm = None


def open_resource_binary(package, resource):
    """Open a package resource in binary mode, compatible with Python 3.8+."""
    try:
        return importlib.resources.files(package).joinpath(resource).open("rb")
    except AttributeError:
        # Python 3.8
        return importlib.resources.open_binary(package, resource)  # pylint: disable=deprecated-method


def open_resource_text(package, resource):
    """Open a package resource in text mode, compatible with Python 3.8+."""
    try:
        return importlib.resources.files(package).joinpath(resource).open("r")
    except AttributeError:
        # Python 3.8
        return importlib.resources.open_text(package, resource)  # pylint: disable=deprecated-method

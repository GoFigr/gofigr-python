"""\
Notebook name/path resolution logic.

Encapsulates all mechanisms for detecting which notebook is running:
VSCode cell IDs, Databricks context, JPY_SESSION_NAME, and the JS proxy fallback.

Copyright (c) 2025, Flagstaff Solutions, LLC
All rights reserved.

"""
import logging
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import unquote, urlparse

from gofigr.compat import get_ipython
from gofigr.databricks import get_dbutils
from gofigr.proxy import run_proxy_async, get_javascript_loader
from gofigr.trap import SuppressDisplayTrap
from gofigr.compat import ipython_display as display


logger = logging.getLogger(__name__)

NOTEBOOK_PATH = "notebook_path"
NOTEBOOK_NAME = "notebook_name"
NOTEBOOK_URL = "url"

PATH_WARNING = "To fix this warning, you can manually specify the notebook name & path in the call to configure(). " \
               "Please see https://gofigr.io/docs/gofigr-python/latest/customization.html#notebook-name-path " \
               "for details."

_ACTIVE_TAB_TITLE = "active_tab_title"


def _parse_path_from_tab_title(title):
    """Parses out the notebook path from the tab/widget title"""
    for line in title.splitlines(keepends=False):
        m = re.match(r'Path:\s*(.*)\s*', line)
        if m:
            return m.group(1)
    return None


@dataclass
class ResolutionEvent:
    """Records a single attempt at resolving notebook metadata."""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    method: str = ""        # "vscode", "databricks", "jpy_session", "proxy", "configure_init"
    success: bool = False
    blocked: bool = False    # True if we blocked waiting for metadata
    duration_ms: float = 0   # how long the attempt took
    detail: str = ""         # additional context


class ResolutionLog:
    """Collects ResolutionEvents for debugging notebook name resolution."""

    def __init__(self):
        self.events = []
        self._resolved_method = None

    def record(self, method, success, blocked=False, duration_ms=0, detail=""):
        """Record a resolution attempt."""
        event = ResolutionEvent(
            method=method,
            success=success,
            blocked=blocked,
            duration_ms=duration_ms,
            detail=detail
        )
        self.events.append(event)

        if success and self._resolved_method is None:
            self._resolved_method = method

        logger.debug("Resolution: method=%s success=%s blocked=%s "
                     "duration=%.1fms detail=%s",
                     method, success, blocked, duration_ms, detail)
        return event

    @property
    def resolved_method(self):
        """The method that first successfully resolved, or None."""
        return self._resolved_method

    @property
    def is_resolved(self):
        """True if any attempt has succeeded."""
        return self._resolved_method is not None

    def summary(self):
        """Human-readable summary for debugging."""
        lines = [f"NotebookName resolution: "
                 f"{'resolved' if self.is_resolved else 'pending'}"
                 f" (via {self._resolved_method or 'N/A'})"]
        for evt in self.events:
            status = "OK" if evt.success else "FAIL"
            blk = " [blocked]" if evt.blocked else ""
            lines.append(f"  {evt.timestamp} {evt.method}: "
                         f"{status}{blk} ({evt.duration_ms:.0f}ms)"
                         f"{' - ' + evt.detail if evt.detail else ''}")
        return "\n".join(lines)


def _get_ip_extension():
    """Returns the IPython GoFigr extension if available, None otherwise."""
    try:
        get_extension = get_ipython().user_ns.get("get_extension")
        return get_extension() if get_extension is not None else None
    except Exception:  # pylint: disable=broad-exception-caught
        return None


def parse_from_vscode():
    """Returns notebook path if running in VSCode"""
    ext = _get_ip_extension()
    if ext is None:
        return None

    try:
        if ext.cell is None or getattr(ext.cell, "cell_id") is None:
            return None
        elif "vscode-notebook-cell:" not in ext.cell.cell_id:
            return None

        m = re.match(r'^vscode-notebook-cell:(.*)#.*$', unquote(ext.cell.cell_id))
        if m is None:
            return None

        notebook_path = m.group(1)
        notebook_name = os.path.basename(notebook_path)

        return {NOTEBOOK_PATH: notebook_path,
                NOTEBOOK_NAME: notebook_name}
    except Exception:  # pylint: disable=broad-exception-caught
        return None


def parse_from_databricks():
    """Returns notebook path if running in Databricks"""
    try:
        # pylint: disable=undefined-variable
        context = get_dbutils(get_ipython()).notebook.entry_point.getDbutils().notebook().getContext()
        nb = context.notebookPath().get()
        return {NOTEBOOK_PATH: nb, NOTEBOOK_NAME: os.path.basename(nb)}
    except Exception as e:  # pylint: disable=broad-exception-caught
        logging.debug(f"Unable to parse notebook metadata from Databricks: {e}")
        return None


def parse_from_jpy_session():
    """Returns notebook path if JPY_SESSION_NAME is set by jupyter_server"""
    session_name = os.environ.get("JPY_SESSION_NAME")
    if session_name:
        return {NOTEBOOK_PATH: session_name,
                NOTEBOOK_NAME: os.path.basename(session_name)}
    return None


def parse_from_proxy(meta):
    """Parse notebook metadata from JavaScript proxy results.

    :param meta: dictionary of proxy metadata
    :return: metadata dict or None
    """
    if 'url' not in meta and _ACTIVE_TAB_TITLE not in meta:
        return None

    notebook_name = None

    # Try parsing the name from the title first
    if _ACTIVE_TAB_TITLE in meta and meta[_ACTIVE_TAB_TITLE] is not None:
        notebook_name = _parse_path_from_tab_title(meta[_ACTIVE_TAB_TITLE])

    # If that doesn't work, try the URL
    if notebook_name is None:
        notebook_name = unquote(urlparse(meta['url']).path.rsplit('/', 1)[-1])

    notebook_dir = get_ipython().starting_dir
    full_path = None

    for candidate_path in [os.path.join(notebook_dir, notebook_name),
                           os.path.join(notebook_dir, os.path.basename(notebook_name)),
                           os.path.join(os.path.dirname(notebook_dir), notebook_name),
                           os.path.join(os.path.dirname(notebook_dir), os.path.basename(notebook_name))]:
        if os.path.exists(candidate_path):
            full_path = candidate_path
            break

    if full_path is None:
        full_path = os.path.join(notebook_dir, notebook_name)
        print(f"The inferred path for the notebook does not exist: {full_path}. {PATH_WARNING}", file=sys.stderr)

    return {NOTEBOOK_PATH: full_path,
            NOTEBOOK_NAME: notebook_name,
            NOTEBOOK_URL: meta.get('url')}


_DETECTION_CHAIN = [
    ("vscode", parse_from_vscode),
    ("databricks", parse_from_databricks),
    ("jpy_session", parse_from_jpy_session),
]


def try_resolve_metadata():
    """Run the synchronous detection chain: VSCode -> Databricks -> JPY_SESSION_NAME.

    :return: tuple of (method_name, metadata_dict) or (None, None)
    """
    for method, func in _DETECTION_CHAIN:
        meta = func()
        if meta is not None:
            return method, meta

    return None, None


class NotebookResolver:
    """Resolves the notebook name/path using available environment signals."""

    def __init__(self, shell, enable_proxy=False):
        self.shell = shell
        self.enable_proxy = enable_proxy
        self.resolution = ResolutionLog()
        self.metadata = None          # resolved notebook metadata dict
        self._proxy = None
        self._wait_for_metadata = None
        self._loader_shown = False

    @property
    def is_resolved(self):
        """True if notebook metadata has been resolved."""
        return self.metadata is not None

    def try_resolve_immediate(self):
        """Synchronous resolution: VSCode -> Databricks -> JPY_SESSION_NAME.
        Called at init time and on each cell boundary."""
        if self.metadata is not None:
            return True

        t0 = time.monotonic()
        method, meta = try_resolve_metadata()
        elapsed = (time.monotonic() - t0) * 1000

        if meta is not None:
            self.metadata = meta
            self.resolution.record(method=method, success=True,
                                   duration_ms=elapsed)
        return self.is_resolved

    def try_resolve_proxy(self, gf, result):
        """Async resolution via JS proxy. Only available in full mode."""
        if not self.enable_proxy or self.is_resolved:
            return

        if gf is not None and not self._loader_shown and "_VSCODE" not in result.info.raw_cell:
            self._proxy, self._wait_for_metadata = run_proxy_async(gf, self._proxy_callback)

            with SuppressDisplayTrap():
                display(get_javascript_loader(gf, self._proxy))
                self._loader_shown = True

        if self.metadata is None and self._wait_for_metadata is not None:
            t0 = time.monotonic()
            self._wait_for_metadata()
            elapsed = (time.monotonic() - t0) * 1000
            success = self.metadata is not None
            self.resolution.record(method="proxy", success=success,
                                   blocked=True, duration_ms=elapsed,
                                   detail="post_run_cell wait")
            self._wait_for_metadata = None

    def _proxy_callback(self, result):
        """Callback invoked by the proxy thread when metadata arrives."""
        if result is not None and hasattr(result, 'metadata'):
            self.metadata = parse_from_proxy(result.metadata)
            self.resolution.record(method="proxy", success=True,
                                   detail="callback received")

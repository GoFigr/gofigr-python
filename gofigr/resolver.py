"""\
Notebook name/path resolution logic.

Encapsulates all mechanisms for detecting which notebook is running:
VSCode cell IDs, Databricks context, JPY_SESSION_NAME, and the JS proxy fallback.

Copyright (c) 2025, Flagstaff Solutions, LLC
All rights reserved.

"""
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime

from gofigr.annotators import NotebookMetadataAnnotator
from gofigr.proxy import run_proxy_async, get_javascript_loader
from gofigr.trap import SuppressDisplayTrap
from gofigr.compat import ipython_display as display


logger = logging.getLogger(__name__)


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
        if self.metadata is None:
            self.metadata = NotebookMetadataAnnotator().try_get_metadata()
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
            self.metadata = result.metadata

    def record_initial_resolution(self):
        """Record which method resolved metadata at configure time."""
        if self.metadata is not None:
            if hasattr(self.shell, 'user_ns') and \
                    "__vsc_ipynb_file__" in self.shell.user_ns:
                method = "vscode"
            else:
                method = "configure_init"
            self.resolution.record(
                method=method, success=True,
                detail="metadata available at configure time")

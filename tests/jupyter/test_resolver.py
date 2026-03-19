"""\
Tests for the NotebookResolver and detection functions.

Copyright (c) 2026, Flagstaff Solutions, LLC
All rights reserved.

"""
import os
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

import pytest

from gofigr.resolver import (
    NotebookResolver,
    ResolutionLog,
    parse_from_vscode,
    parse_from_databricks,
    parse_from_jpy_session,
    parse_from_proxy,
    try_resolve_metadata,
    _parse_path_from_tab_title,
    NOTEBOOK_PATH,
    NOTEBOOK_NAME,
    NOTEBOOK_URL,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class FakeShell:
    """Minimal shell stub for NotebookResolver."""
    user_ns = {}


def _make_ext_with_cell(cell_id):
    """Returns a fake extension whose .cell.cell_id is the given string."""
    return SimpleNamespace(cell=SimpleNamespace(cell_id=cell_id))


# ---------------------------------------------------------------------------
# _parse_path_from_tab_title
# ---------------------------------------------------------------------------

class TestParsePathFromTabTitle:
    def test_simple_path(self):
        assert _parse_path_from_tab_title("Path: my_notebook.ipynb") == "my_notebook.ipynb"

    def test_multiline(self):
        title = "Title: Something\nPath: notebooks/demo.ipynb\nOther: stuff"
        assert _parse_path_from_tab_title(title) == "notebooks/demo.ipynb"

    def test_no_path(self):
        assert _parse_path_from_tab_title("no path here") is None

    def test_empty(self):
        assert _parse_path_from_tab_title("") is None


# ---------------------------------------------------------------------------
# parse_from_jpy_session
# ---------------------------------------------------------------------------

class TestParseFromJpySession:
    def test_returns_metadata_when_set(self):
        with patch.dict(os.environ, {"JPY_SESSION_NAME": "/home/user/nb.ipynb"}):
            result = parse_from_jpy_session()
        assert result[NOTEBOOK_PATH] == "/home/user/nb.ipynb"
        assert result[NOTEBOOK_NAME] == "nb.ipynb"

    def test_returns_none_when_unset(self):
        with patch.dict(os.environ, {}, clear=True):
            # Ensure JPY_SESSION_NAME is not set
            os.environ.pop("JPY_SESSION_NAME", None)
            result = parse_from_jpy_session()
        assert result is None

    def test_nested_path(self):
        with patch.dict(os.environ, {"JPY_SESSION_NAME": "/srv/notebooks/project/analysis.ipynb"}):
            result = parse_from_jpy_session()
        assert result[NOTEBOOK_PATH] == "/srv/notebooks/project/analysis.ipynb"
        assert result[NOTEBOOK_NAME] == "analysis.ipynb"


# ---------------------------------------------------------------------------
# parse_from_vscode
# ---------------------------------------------------------------------------

class TestParseFromVscode:
    def test_valid_vscode_cell_id(self):
        cell_id = "vscode-notebook-cell:/Users/dev/my_notebook.ipynb#W0sZmlsZQ"
        ext = _make_ext_with_cell(cell_id)

        with patch("gofigr.resolver._get_ip_extension", return_value=ext):
            result = parse_from_vscode()

        assert result[NOTEBOOK_PATH] == "/Users/dev/my_notebook.ipynb"
        assert result[NOTEBOOK_NAME] == "my_notebook.ipynb"

    def test_url_encoded_path(self):
        cell_id = "vscode-notebook-cell:/Users/dev/my%20notebook.ipynb#W0sZmlsZQ"
        ext = _make_ext_with_cell(cell_id)

        with patch("gofigr.resolver._get_ip_extension", return_value=ext):
            result = parse_from_vscode()

        assert result[NOTEBOOK_PATH] == "/Users/dev/my notebook.ipynb"
        assert result[NOTEBOOK_NAME] == "my notebook.ipynb"

    def test_no_extension_returns_none(self):
        with patch("gofigr.resolver._get_ip_extension", return_value=None):
            assert parse_from_vscode() is None

    def test_no_cell_returns_none(self):
        ext = SimpleNamespace(cell=None)
        with patch("gofigr.resolver._get_ip_extension", return_value=ext):
            assert parse_from_vscode() is None

    def test_non_vscode_cell_id_returns_none(self):
        ext = _make_ext_with_cell("some-other-cell-id")
        with patch("gofigr.resolver._get_ip_extension", return_value=ext):
            assert parse_from_vscode() is None

    def test_malformed_vscode_cell_id_returns_none(self):
        ext = _make_ext_with_cell("vscode-notebook-cell:no-hash-here")
        with patch("gofigr.resolver._get_ip_extension", return_value=ext):
            assert parse_from_vscode() is None


# ---------------------------------------------------------------------------
# parse_from_databricks
# ---------------------------------------------------------------------------

class TestParseFromDatabricks:
    def _mock_dbutils(self, notebook_path):
        """Builds a mock dbutils chain that returns the given notebook path."""
        mock_context = MagicMock()
        mock_context.notebookPath.return_value.get.return_value = notebook_path

        dbutils = MagicMock()
        dbutils.notebook.entry_point.getDbutils.return_value \
            .notebook.return_value.getContext.return_value = mock_context
        return dbutils

    def test_returns_metadata(self):
        dbutils = self._mock_dbutils("/Workspace/Users/me/analysis")

        with patch("gofigr.resolver.get_dbutils", return_value=dbutils), \
             patch("gofigr.resolver.get_ipython", return_value=MagicMock()):
            result = parse_from_databricks()

        assert result[NOTEBOOK_PATH] == "/Workspace/Users/me/analysis"
        assert result[NOTEBOOK_NAME] == "analysis"

    def test_returns_none_outside_databricks(self):
        with patch("gofigr.resolver.get_dbutils", side_effect=Exception("not databricks")), \
             patch("gofigr.resolver.get_ipython", return_value=MagicMock()):
            assert parse_from_databricks() is None


# ---------------------------------------------------------------------------
# parse_from_proxy
# ---------------------------------------------------------------------------

class TestParseFromProxy:
    def test_url_based_resolution(self, tmp_path):
        nb_file = tmp_path / "demo.ipynb"
        nb_file.touch()

        mock_ip = MagicMock()
        mock_ip.starting_dir = str(tmp_path)

        with patch("gofigr.resolver.get_ipython", return_value=mock_ip):
            result = parse_from_proxy({"url": "http://localhost:8888/notebooks/demo.ipynb"})

        assert result[NOTEBOOK_NAME] == "demo.ipynb"
        assert result[NOTEBOOK_PATH] == str(nb_file)
        assert result[NOTEBOOK_URL] == "http://localhost:8888/notebooks/demo.ipynb"

    def test_title_based_resolution(self, tmp_path):
        nb_file = tmp_path / "from_title.ipynb"
        nb_file.touch()

        mock_ip = MagicMock()
        mock_ip.starting_dir = str(tmp_path)

        meta = {
            "url": "http://localhost:8888/notebooks/wrong.ipynb",
            "active_tab_title": "Path: from_title.ipynb",
        }
        with patch("gofigr.resolver.get_ipython", return_value=mock_ip):
            result = parse_from_proxy(meta)

        assert result[NOTEBOOK_NAME] == "from_title.ipynb"
        assert result[NOTEBOOK_PATH] == str(nb_file)

    def test_returns_none_without_url_or_title(self):
        assert parse_from_proxy({}) is None
        assert parse_from_proxy({"other_key": "value"}) is None


# ---------------------------------------------------------------------------
# try_resolve_metadata  (detection chain ordering)
# ---------------------------------------------------------------------------

def _mock_chain(**returns):
    """Build a patched _DETECTION_CHAIN from keyword args like vscode=meta_dict."""
    chain = []
    for method in ("vscode", "databricks", "jpy_session"):
        val = returns.get(method)
        chain.append((method, lambda v=val: v))
    return chain


class TestTryResolveMetadata:
    def test_vscode_wins_over_others(self):
        vsc = {NOTEBOOK_PATH: "/vsc", NOTEBOOK_NAME: "vsc.ipynb"}
        jpy = {NOTEBOOK_PATH: "/jpy", NOTEBOOK_NAME: "jpy.ipynb"}

        with patch("gofigr.resolver._DETECTION_CHAIN",
                    _mock_chain(vscode=vsc, jpy_session=jpy)):
            method, meta = try_resolve_metadata()

        assert method == "vscode"
        assert meta == vsc

    def test_databricks_if_no_vscode(self):
        db = {NOTEBOOK_PATH: "/db", NOTEBOOK_NAME: "db"}

        with patch("gofigr.resolver._DETECTION_CHAIN",
                    _mock_chain(databricks=db)):
            method, meta = try_resolve_metadata()

        assert method == "databricks"
        assert meta == db

    def test_jpy_session_if_no_vscode_or_databricks(self):
        jpy = {NOTEBOOK_PATH: "/jpy", NOTEBOOK_NAME: "jpy.ipynb"}

        with patch("gofigr.resolver._DETECTION_CHAIN",
                    _mock_chain(jpy_session=jpy)):
            method, meta = try_resolve_metadata()

        assert method == "jpy_session"
        assert meta == jpy

    def test_returns_none_tuple_when_nothing_matches(self):
        with patch("gofigr.resolver._DETECTION_CHAIN", _mock_chain()):
            method, meta = try_resolve_metadata()

        assert method is None
        assert meta is None


# ---------------------------------------------------------------------------
# ResolutionLog
# ---------------------------------------------------------------------------

class TestResolutionLog:
    def test_empty_log(self):
        log = ResolutionLog()
        assert not log.is_resolved
        assert log.resolved_method is None
        assert "pending" in log.summary()

    def test_first_success_wins(self):
        log = ResolutionLog()
        log.record("vscode", success=False)
        log.record("jpy_session", success=True)
        log.record("proxy", success=True)

        assert log.is_resolved
        assert log.resolved_method == "jpy_session"
        assert len(log.events) == 3

    def test_summary_format(self):
        log = ResolutionLog()
        log.record("vscode", success=True, duration_ms=1.5, detail="found")
        summary = log.summary()
        assert "resolved" in summary
        assert "vscode" in summary
        assert "found" in summary


# ---------------------------------------------------------------------------
# NotebookResolver
# ---------------------------------------------------------------------------

class TestNotebookResolver:
    def test_resolve_immediate_jpy(self):
        jpy = {NOTEBOOK_PATH: "/jpy/nb.ipynb", NOTEBOOK_NAME: "nb.ipynb"}

        resolver = NotebookResolver(FakeShell(), enable_proxy=False)
        assert not resolver.is_resolved

        with patch("gofigr.resolver.try_resolve_metadata", return_value=("jpy_session", jpy)):
            resolved = resolver.try_resolve_immediate()

        assert resolved
        assert resolver.is_resolved
        assert resolver.metadata is jpy
        assert resolver.resolution.resolved_method == "jpy_session"

    def test_resolve_immediate_vscode(self):
        vsc = {NOTEBOOK_PATH: "/vsc/nb.ipynb", NOTEBOOK_NAME: "nb.ipynb"}

        resolver = NotebookResolver(FakeShell(), enable_proxy=False)

        with patch("gofigr.resolver.try_resolve_metadata", return_value=("vscode", vsc)):
            resolver.try_resolve_immediate()

        assert resolver.resolution.resolved_method == "vscode"

    def test_resolve_immediate_no_match(self):
        resolver = NotebookResolver(FakeShell(), enable_proxy=False)

        with patch("gofigr.resolver.try_resolve_metadata", return_value=(None, None)):
            resolved = resolver.try_resolve_immediate()

        assert not resolved
        assert not resolver.is_resolved
        assert resolver.resolution.resolved_method is None
        assert len(resolver.resolution.events) == 0

    def test_resolve_immediate_skips_if_already_resolved(self):
        resolver = NotebookResolver(FakeShell(), enable_proxy=False)
        resolver.metadata = {NOTEBOOK_PATH: "/already", NOTEBOOK_NAME: "already.ipynb"}

        with patch("gofigr.resolver.try_resolve_metadata") as mock:
            resolved = resolver.try_resolve_immediate()

        assert resolved
        mock.assert_not_called()

    def test_proxy_skipped_when_disabled(self):
        resolver = NotebookResolver(FakeShell(), enable_proxy=False)

        with patch("gofigr.resolver.run_proxy_async") as mock:
            resolver.try_resolve_proxy(MagicMock(), MagicMock())

        mock.assert_not_called()

    def test_proxy_skipped_when_already_resolved(self):
        resolver = NotebookResolver(FakeShell(), enable_proxy=True)
        resolver.metadata = {NOTEBOOK_PATH: "/done", NOTEBOOK_NAME: "done.ipynb"}

        with patch("gofigr.resolver.run_proxy_async") as mock:
            resolver.try_resolve_proxy(MagicMock(), MagicMock())

        mock.assert_not_called()

    def test_metadata_setter_makes_resolved(self):
        resolver = NotebookResolver(FakeShell(), enable_proxy=False)
        assert not resolver.is_resolved

        resolver.metadata = {NOTEBOOK_PATH: "/x", NOTEBOOK_NAME: "x.ipynb"}
        assert resolver.is_resolved

    def test_multiple_resolve_calls_idempotent(self):
        first = {NOTEBOOK_PATH: "/first", NOTEBOOK_NAME: "first.ipynb"}
        second = {NOTEBOOK_PATH: "/second", NOTEBOOK_NAME: "second.ipynb"}

        resolver = NotebookResolver(FakeShell(), enable_proxy=False)

        with patch("gofigr.resolver.try_resolve_metadata", return_value=("jpy_session", first)):
            resolver.try_resolve_immediate()

        with patch("gofigr.resolver.try_resolve_metadata", return_value=("vscode", second)):
            resolver.try_resolve_immediate()

        # First resolution should stick
        assert resolver.metadata is first
        assert resolver.resolution.resolved_method == "jpy_session"


# ---------------------------------------------------------------------------
# End-to-end: JPY_SESSION_NAME with real env var
# ---------------------------------------------------------------------------

class TestEndToEnd:
    def test_jpy_session_e2e(self):
        """Full flow: set env var -> resolver picks it up -> records jpy_session."""
        with patch.dict(os.environ, {"JPY_SESSION_NAME": "/srv/work/demo.ipynb"}), \
             patch("gofigr.resolver.parse_from_vscode", return_value=None), \
             patch("gofigr.resolver.parse_from_databricks", return_value=None):
            resolver = NotebookResolver(FakeShell(), enable_proxy=False)
            resolver.try_resolve_immediate()

        assert resolver.is_resolved
        assert resolver.metadata[NOTEBOOK_PATH] == "/srv/work/demo.ipynb"
        assert resolver.metadata[NOTEBOOK_NAME] == "demo.ipynb"
        assert resolver.resolution.resolved_method == "jpy_session"
        assert len(resolver.resolution.events) == 1

    def test_vscode_e2e(self):
        """Full flow: mock VSCode cell_id -> resolver records vscode."""
        cell_id = "vscode-notebook-cell:/Users/dev/analysis.ipynb#W2sZmlsZQ"
        ext = _make_ext_with_cell(cell_id)

        with patch("gofigr.resolver._get_ip_extension", return_value=ext), \
             patch.dict(os.environ, {}, clear=False):
            os.environ.pop("JPY_SESSION_NAME", None)
            resolver = NotebookResolver(FakeShell(), enable_proxy=False)
            resolver.try_resolve_immediate()

        assert resolver.is_resolved
        assert resolver.metadata[NOTEBOOK_PATH] == "/Users/dev/analysis.ipynb"
        assert resolver.resolution.resolved_method == "vscode"

    def test_databricks_e2e(self):
        """Full flow: mock Databricks context -> resolver records databricks."""
        mock_context = MagicMock()
        mock_context.notebookPath.return_value.get.return_value = "/Workspace/Users/me/pipeline"

        dbutils = MagicMock()
        dbutils.notebook.entry_point.getDbutils.return_value \
            .notebook.return_value.getContext.return_value = mock_context

        with patch("gofigr.resolver._get_ip_extension", return_value=None), \
             patch("gofigr.resolver.get_dbutils", return_value=dbutils), \
             patch("gofigr.resolver.get_ipython", return_value=MagicMock()), \
             patch.dict(os.environ, {}, clear=False):
            os.environ.pop("JPY_SESSION_NAME", None)
            resolver = NotebookResolver(FakeShell(), enable_proxy=False)
            resolver.try_resolve_immediate()

        assert resolver.is_resolved
        assert resolver.metadata[NOTEBOOK_PATH] == "/Workspace/Users/me/pipeline"
        assert resolver.metadata[NOTEBOOK_NAME] == "pipeline"
        assert resolver.resolution.resolved_method == "databricks"

    def test_nothing_resolves(self):
        """No detection method succeeds -> resolver stays unresolved."""
        with patch("gofigr.resolver._get_ip_extension", return_value=None), \
             patch("gofigr.resolver.get_dbutils", side_effect=Exception("nope")), \
             patch("gofigr.resolver.get_ipython", return_value=MagicMock()), \
             patch.dict(os.environ, {}, clear=False):
            os.environ.pop("JPY_SESSION_NAME", None)
            resolver = NotebookResolver(FakeShell(), enable_proxy=False)
            resolver.try_resolve_immediate()

        assert not resolver.is_resolved
        assert resolver.metadata is None
        assert resolver.resolution.resolved_method is None

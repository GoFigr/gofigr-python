"""\
Tests for the GoFigr Jupyter extension using the JupyterHarness.

Covers deferred analysis-scoping, auto_publish reconfiguration, and extension
lifecycle, all exercised through the full pre_run_cell/post_run_cell event cycle.

Copyright (c) 2026, Flagstaff Solutions, LLC
All rights reserved.

"""
import os
import uuid
from pathlib import Path
from unittest import TestCase

from gofigr.trap import GfDisplayPublisher
from tests.jupyter_harness import JupyterHarness
from tests.test_client import make_gf

DATA_DIR = Path(__file__).parent / "data"
BLOB_PATH = str(DATA_DIR / "blob.bin")


def _configure_cell(analysis_expr="NotebookName()", auto_publish=False):
    """Returns the code for a configure() cell.

    Reads credentials from env vars at test time and injects them via os.environ
    references so special characters in passwords are not mangled.
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


class TestDeferredSync(TestCase):
    def setUp(self):
        self.harness = JupyterHarness(notebook_name="test_deferred_sync.ipynb")
        self.harness.start()

    def tearDown(self):
        self.harness.stop()

    def _load_and_configure(self, analysis_expr="NotebookName()"):
        result = self.harness.run_cell("%load_ext gofigr")
        self.assertFalse(result.error_in_exec, f"load_ext failed: {result.error_in_exec}")

        result = self.harness.run_cell(_configure_cell(analysis_expr))
        self.assertFalse(result.error_in_exec, f"configure failed: {result.error_in_exec}")

    def test_deferred_sync_resolves_after_cell(self):
        """sync_revision with NotebookName() defers, then post_run_cell resolves and processes."""
        self._load_and_configure()
        self.harness.inject_notebook_metadata()

        ext = self.harness.get_extension()
        gf = ext.gf

        # Analysis should be pending before the next cell runs
        self.assertTrue(gf.analysis_pending)

        # Run a cell that triggers sync_revision — deferred inside the cell,
        # but post_run_cell fires resolve_analysis which processes deferred syncs.
        result = self.harness.run_cell(f"gf.sync.sync_revision('{BLOB_PATH}')")
        self.assertFalse(result.error_in_exec, f"sync_revision cell failed: {result.error_in_exec}")

        # After post_run_cell, deferred syncs should be processed
        self.assertEqual(len(gf.sync.deferred_syncs), 0, "Deferred syncs not processed")
        self.assertGreater(len(gf.sync.asset_log), 0, "Asset log should have an entry")
        self.assertFalse(gf.analysis_pending, "Analysis should no longer be pending")
        self.assertIsNotNone(gf.analysis_id, "Analysis ID should be set")

    def test_immediate_sync_with_explicit_analysis(self):
        """With an explicit analysis name, sync_revision happens immediately (no deferral)."""
        self._load_and_configure(analysis_expr="'Test Immediate Sync'")

        ext = self.harness.get_extension()
        gf = ext.gf

        self.assertFalse(gf.analysis_pending, "Analysis should not be pending with explicit name")

        result = self.harness.run_cell(f"rev = gf.sync.sync_revision('{BLOB_PATH}')")
        self.assertFalse(result.error_in_exec, f"sync_revision cell failed: {result.error_in_exec}")

        rev = self.harness.shell.user_ns.get("rev")
        self.assertIsNotNone(rev, "sync_revision should return a revision immediately")
        self.assertEqual(len(gf.sync.deferred_syncs), 0, "No deferred syncs expected")

    def test_multiple_deferred_syncs_same_file(self):
        """Two sync_revision calls on the same file should dedup after resolution."""
        self._load_and_configure()
        self.harness.inject_notebook_metadata()

        ext = self.harness.get_extension()
        gf = ext.gf

        # Run a cell that calls sync_revision twice on the same file
        result = self.harness.run_cell(
            f"gf.sync.sync_revision('{BLOB_PATH}')\n"
            f"gf.sync.sync_revision('{BLOB_PATH}')"
        )
        self.assertFalse(result.error_in_exec, f"cell failed: {result.error_in_exec}")

        # After resolution, deferred syncs should be empty
        self.assertEqual(len(gf.sync.deferred_syncs), 0, "Deferred syncs not processed")
        # Only one asset entry (dedup by asset api_id in asset_log dict)
        self.assertEqual(len(gf.sync.asset_log), 1, "Should have exactly one asset entry (dedup)")

    def test_load_and_configure_same_cell(self):
        """Loading extension and configuring in the same cell should work."""
        code = "%load_ext gofigr\n" + _configure_cell()
        result = self.harness.run_cell(code)
        self.assertFalse(result.error_in_exec, f"combined cell failed: {result.error_in_exec}")

        self.harness.inject_notebook_metadata()

        ext = self.harness.get_extension()
        self.assertIsNotNone(ext, "Extension should be loaded")
        self.assertTrue(ext.configured, "Extension should be configured")

        # Run another cell to trigger resolve_analysis via post_run_cell
        result = self.harness.run_cell("pass")
        self.assertFalse(result.error_in_exec)

        self.assertFalse(ext.gf.analysis_pending, "Analysis should be resolved after next cell")

    def test_extension_reload(self):
        """Reloading the extension should reinitialize cleanly."""
        self._load_and_configure(analysis_expr="'Test Reload'")

        ext1 = self.harness.get_extension()
        self.assertTrue(ext1.configured)

        # Reload
        result = self.harness.run_cell("%reload_ext gofigr")
        self.assertFalse(result.error_in_exec)

        ext2 = self.harness.get_extension()
        self.assertIsNot(ext1, ext2, "Should be a new extension instance")
        self.assertFalse(ext2.configured, "New extension should not be configured yet")

        # Re-configure
        result = self.harness.run_cell(_configure_cell(analysis_expr="'Test Reload 2'"))
        self.assertFalse(result.error_in_exec, f"re-configure failed: {result.error_in_exec}")

        self.assertTrue(ext2.configured, "Extension should be configured after re-configure")
        self.assertIsNotNone(ext2.gf.analysis_id)

    def test_auto_publish_false_after_reconfigure(self):
        """Reconfiguring with auto_publish=False must stop capturing figures.

        Regression test for a bug where GfDisplayPublisher kept a stale display_trap
        reference after reconfigure, so the old extension (with auto_publish=True)
        continued to capture figures.
        """
        analysis_name = f"test_auto_publish_{uuid.uuid4().hex[:8]}"
        gf_cleanup = make_gf()

        try:
            # First configure with auto_publish=True
            result = self.harness.run_cell("%load_ext gofigr")
            self.assertFalse(result.error_in_exec)
            result = self.harness.run_cell(
                _configure_cell(analysis_expr=f"'{analysis_name}'", auto_publish=True))
            self.assertFalse(result.error_in_exec, f"configure failed: {result.error_in_exec}")

            ext = self.harness.get_extension()
            self.assertTrue(ext.auto_publish)

            # Publish a figure with auto_publish=True to prove auto-capture works.
            # We use display(fig) instead of plt.show() because bare InteractiveShell
            # doesn't have a GUI event loop — display() goes through the display
            # publisher which is where GfDisplayPublisher traps figures.
            result = self.harness.run_cell(
                "import matplotlib\n"
                "matplotlib.use('agg')\n"
                "import matplotlib.pyplot as plt\n"
                "from IPython.display import display\n"
                "fig = plt.figure()\n"
                "plt.plot([1, 2, 3])\n"
                "plt.title('First')\n"
                "display(fig)")
            self.assertFalse(result.error_in_exec)

            analysis = ext.publisher.analysis
            analysis.fetch()
            figures_before = list(analysis.figures or [])
            self.assertGreater(len(figures_before), 0,
                               "auto_publish=True should have captured the figure")

            # Now reconfigure with auto_publish=False (same analysis)
            result = self.harness.run_cell(
                _configure_cell(analysis_expr=f"'{analysis_name}'", auto_publish=False))
            self.assertFalse(result.error_in_exec, f"reconfigure failed: {result.error_in_exec}")

            ext = self.harness.get_extension()
            self.assertFalse(ext.auto_publish)

            # Verify the display trap was updated to the new extension
            display_pub = self.harness.shell.display_pub
            self.assertIsInstance(display_pub, GfDisplayPublisher)
            self.assertEqual(display_pub.display_trap, ext.display_trap,
                             "display_trap should point to the current extension")

            # Create another figure — should NOT be auto-published
            result = self.harness.run_cell(
                "fig2 = plt.figure()\n"
                "plt.plot([4, 5, 6])\n"
                "plt.title('Second')\n"
                "display(fig2)")
            self.assertFalse(result.error_in_exec)

            analysis.fetch()
            figures_after = list(analysis.figures or [])
            self.assertEqual(len(figures_after), len(figures_before),
                             "auto_publish=False should not have captured the second figure")
        finally:
            # Clean up: delete the analysis we created
            try:
                ana = gf_cleanup.primary_workspace.get_analysis(name=analysis_name)
                ana.delete(delete=True)
            except Exception:  # pylint: disable=broad-exception-caught
                pass

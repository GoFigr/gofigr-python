"""\
Tests for deferred analysis-scoping of assets when using NotebookName().

Copyright (c) 2026, Flagstaff Solutions, LLC
All rights reserved.

"""
from tests.jupyter.conftest import BLOB_PATH, configure_cell, load_and_configure


class TestDeferredSync:
    def test_deferred_sync_resolves_after_cell(self, harness):
        """sync_revision with NotebookName() defers, then post_run_cell resolves and processes."""
        load_and_configure(harness)
        harness.inject_notebook_metadata()

        ext = harness.get_extension()
        gf = ext.gf

        # Analysis should be pending before the next cell runs
        assert gf.analysis_pending

        # Run a cell that triggers sync_revision — deferred inside the cell,
        # but post_run_cell fires resolve_analysis which processes deferred syncs.
        result = harness.run_cell(f"gf.sync.sync_revision('{BLOB_PATH}')")
        assert not result.error_in_exec, f"sync_revision cell failed: {result.error_in_exec}"

        # After post_run_cell, deferred syncs should be processed
        assert len(gf.sync.deferred_syncs) == 0, "Deferred syncs not processed"
        assert len(gf.sync.asset_log) > 0, "Asset log should have an entry"
        assert not gf.analysis_pending, "Analysis should no longer be pending"
        assert gf.analysis_id is not None, "Analysis ID should be set"

    def test_immediate_sync_with_explicit_analysis(self, harness):
        """With an explicit analysis name, sync_revision happens immediately (no deferral)."""
        load_and_configure(harness, analysis_expr="'Test Immediate Sync'")

        ext = harness.get_extension()
        gf = ext.gf

        assert not gf.analysis_pending, "Analysis should not be pending with explicit name"

        result = harness.run_cell(f"rev = gf.sync.sync_revision('{BLOB_PATH}')")
        assert not result.error_in_exec, f"sync_revision cell failed: {result.error_in_exec}"

        rev = harness.shell.user_ns.get("rev")
        assert rev is not None, "sync_revision should return a revision immediately"
        assert len(gf.sync.deferred_syncs) == 0, "No deferred syncs expected"

    def test_multiple_deferred_syncs_same_file(self, harness):
        """Two sync_revision calls on the same file should dedup after resolution."""
        load_and_configure(harness)
        harness.inject_notebook_metadata()

        ext = harness.get_extension()
        gf = ext.gf

        # Run a cell that calls sync_revision twice on the same file
        result = harness.run_cell(
            f"gf.sync.sync_revision('{BLOB_PATH}')\n"
            f"gf.sync.sync_revision('{BLOB_PATH}')"
        )
        assert not result.error_in_exec, f"cell failed: {result.error_in_exec}"

        # After resolution, deferred syncs should be empty
        assert len(gf.sync.deferred_syncs) == 0, "Deferred syncs not processed"
        # Only one asset entry (dedup by asset api_id in asset_log dict)
        assert len(gf.sync.asset_log) == 1, "Should have exactly one asset entry (dedup)"


class TestExtensionLifecycle:
    def test_load_and_configure_same_cell(self, harness):
        """Loading extension and configuring in the same cell should work."""
        code = "%load_ext gofigr\n" + configure_cell()
        result = harness.run_cell(code)
        assert not result.error_in_exec, f"combined cell failed: {result.error_in_exec}"

        harness.inject_notebook_metadata()

        ext = harness.get_extension()
        assert ext is not None, "Extension should be loaded"
        assert ext.configured, "Extension should be configured"

        # Run another cell to trigger resolve_analysis via post_run_cell
        result = harness.run_cell("pass")
        assert not result.error_in_exec

        assert not ext.gf.analysis_pending, "Analysis should be resolved after next cell"

    def test_extension_reload(self, harness):
        """Reloading the extension should reinitialize cleanly."""
        load_and_configure(harness, analysis_expr="'Test Reload'")

        ext1 = harness.get_extension()
        assert ext1.configured

        # Reload
        result = harness.run_cell("%reload_ext gofigr")
        assert not result.error_in_exec

        ext2 = harness.get_extension()
        assert ext1 is not ext2, "Should be a new extension instance"
        assert not ext2.configured, "New extension should not be configured yet"

        # Re-configure
        result = harness.run_cell(configure_cell(analysis_expr="'Test Reload 2'"))
        assert not result.error_in_exec, f"re-configure failed: {result.error_in_exec}"

        assert ext2.configured, "Extension should be configured after re-configure"
        assert ext2.gf.analysis_id is not None

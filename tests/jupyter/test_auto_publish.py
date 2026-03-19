"""\
Tests for auto_publish behavior, including reconfiguration.

Copyright (c) 2026, Flagstaff Solutions, LLC
All rights reserved.

"""
import uuid

from gofigr.trap import GfDisplayPublisher
from tests.jupyter.conftest import configure_cell, load_and_configure
from tests.test_client import make_gf


class TestAutoPublish:
    def test_auto_publish_false_after_reconfigure(self, harness):
        """Reconfiguring with auto_publish=False must stop capturing figures.

        Regression test for a bug where GfDisplayPublisher kept a stale display_trap
        reference after reconfigure, so the old extension (with auto_publish=True)
        continued to capture figures.
        """
        analysis_name = f"test_auto_publish_{uuid.uuid4().hex[:8]}"
        gf_cleanup = make_gf()

        try:
            # First configure with auto_publish=True
            load_and_configure(harness, analysis_expr=f"'{analysis_name}'",
                               auto_publish=True)

            ext = harness.get_extension()
            assert ext.auto_publish

            # Publish a figure with auto_publish=True to prove auto-capture works.
            # We use display(fig) instead of plt.show() because bare InteractiveShell
            # doesn't have a GUI event loop — display() goes through the display
            # publisher which is where GfDisplayPublisher traps figures.
            result = harness.run_cell(
                "import matplotlib\n"
                "matplotlib.use('agg')\n"
                "import matplotlib.pyplot as plt\n"
                "from IPython.display import display\n"
                "fig = plt.figure()\n"
                "plt.plot([1, 2, 3])\n"
                "plt.title('First')\n"
                "display(fig)")
            assert not result.error_in_exec

            analysis = ext.publisher.analysis
            analysis.fetch()
            figures_before = list(analysis.figures or [])
            assert len(figures_before) > 0, \
                "auto_publish=True should have captured the figure"

            # Now reconfigure with auto_publish=False (same analysis)
            result = harness.run_cell(
                configure_cell(analysis_expr=f"'{analysis_name}'",
                               auto_publish=False))
            assert not result.error_in_exec, \
                f"reconfigure failed: {result.error_in_exec}"

            ext = harness.get_extension()
            assert not ext.auto_publish

            # Verify the display trap was updated to the new extension
            display_pub = harness.shell.display_pub
            assert isinstance(display_pub, GfDisplayPublisher)
            assert display_pub.display_trap == ext.display_trap, \
                "display_trap should point to the current extension"

            # Create another figure — should NOT be auto-published
            result = harness.run_cell(
                "fig2 = plt.figure()\n"
                "plt.plot([4, 5, 6])\n"
                "plt.title('Second')\n"
                "display(fig2)")
            assert not result.error_in_exec

            analysis.fetch()
            figures_after = list(analysis.figures or [])
            assert len(figures_after) == len(figures_before), \
                "auto_publish=False should not have captured the second figure"
        finally:
            # Clean up: delete the analysis we created
            try:
                ana = gf_cleanup.primary_workspace.get_analysis(
                    name=analysis_name)
                ana.delete(delete=True)
            except Exception:  # pylint: disable=broad-exception-caught
                pass

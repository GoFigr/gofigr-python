"""\
Reusable test harness for simulating Jupyter cell execution without a browser or Jupyter server.

Uses IPython's InteractiveShell.run_cell() which fires the full pre_run_cell/post_run_cell event cycle.
The gofigr extension hooks into exactly these events, so this gives us the complete event flow.

Copyright (c) 2026, Flagstaff Solutions, LLC
All rights reserved.

"""
import builtins

from IPython.core.interactiveshell import InteractiveShell


class JupyterHarness:
    """Simulates a Jupyter notebook environment for testing the GoFigr extension.

    Typical usage::

        harness = JupyterHarness()
        harness.start()

        harness.run_cell("%load_ext gofigr")
        harness.run_cell("configure(api_key=..., analysis=NotebookName())")
        harness.inject_notebook_metadata()

        harness.run_cell("gf.sync.sync_revision('tests/data/blob.bin')")
        # ... assertions ...

        harness.stop()
    """

    def __init__(self, notebook_name="test_notebook.ipynb"):
        self.notebook_name = notebook_name
        self.shell = None
        self._original_get_ipython = None

    def start(self):
        """Creates an InteractiveShell and patches builtins.get_ipython so gofigr internals find it."""
        self.shell = InteractiveShell.instance()
        self._original_get_ipython = getattr(builtins, 'get_ipython', None)
        builtins.get_ipython = self.shell.get_ipython
        return self

    def run_cell(self, code):
        """Runs a cell through the shell, firing pre_run_cell/post_run_cell events."""
        if self.shell is None:
            raise RuntimeError("Harness not started. Call start() first.")
        return self.shell.run_cell(code, store_history=True)

    def inject_notebook_metadata(self):
        """Injects resolved notebook metadata to bypass the JS proxy.

        Must be called after configure() but before the next run_cell() so that
        post_run_cell -> resolve_analysis() can resolve NotebookName.
        """
        from gofigr.resolver import NOTEBOOK_PATH, NOTEBOOK_NAME
        ext = self.get_extension()
        if ext is not None:
            ext.notebook_metadata = {
                NOTEBOOK_PATH: self.notebook_name,
                NOTEBOOK_NAME: self.notebook_name,
            }

    def get_extension(self):
        """Returns the _GoFigrExtension instance (or None if not loaded yet)."""
        if self.shell is None:
            return None
        return self.shell.user_ns.get("_GF_EXTENSION")

    def stop(self):
        """Tears down the shell and restores builtins.get_ipython."""
        if self._original_get_ipython is not None:
            builtins.get_ipython = self._original_get_ipython
        elif hasattr(builtins, 'get_ipython'):
            del builtins.get_ipython

        if self.shell is not None:
            InteractiveShell.clear_instance()
            self.shell = None

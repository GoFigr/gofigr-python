"""\
Copyright (c) 2024, Flagstaff Solutions, LLC
All rights reserved.

"""
import inspect
import io
import sys

import plotnine

from gofigr.backends import GoFigrBackend, get_all_function_arguments
from gofigr.backends.matplotlib import SuppressPltWarnings


class PlotnineBackend(GoFigrBackend):
    """\
    MatplotLib backend for GoFigr.

    """
    def get_backend_name(self):
        return "plotnine"

    def is_compatible(self, fig):
        return isinstance(fig, plotnine.ggplot)

    def is_interactive(self, fig):
        return False

    def find_figures(self, shell, data):
        frames = inspect.stack()
        # Walk through the stack in *reverse* order (from top to bottom), to find the first call
        # in case display() was called recursively
        for f in reversed(frames):
            if ("ipython_display" in f.function or "draw" in f.function) and f.filename.endswith("ggplot.py"):
                for arg_value in get_all_function_arguments(f):
                    if self.is_compatible(arg_value):
                        yield arg_value

                break

    def get_default_figure(self, silent=False):
        if not silent:
            print("plotnine does not have a default figure. Please specify a figure to publish.", file=sys.stderr)

    def get_title(self, fig):
        return fig.labels.title

    def figure_to_bytes(self, fig, fmt, params):
        with SuppressPltWarnings():
            bio = io.BytesIO()
            fig.save(bio, format=fmt, verbose=False, **params)

            bio.seek(0)
            return bio.read()

    def close(self, fig):
        pass

    def get_supported_image_formats(self):
        return ["png", "eps", "pdf", "jpeg", "jpg", "svg", "tiff"]

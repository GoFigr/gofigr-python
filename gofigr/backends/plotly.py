"""\
Copyright (c) 2023, Flagstaff Solutions, LLC
All rights reserved.

"""
import sys

from gofigr.backends import GoFigrBackend
import plotly.graph_objects as go


class PlotlyBackend(GoFigrBackend):
    """Plotly backend for GoFigr"""
    def is_compatible(self, fig):
        return isinstance(fig, go.Figure)

    def find_figures(self, shell):
        for name, obj in shell.user_ns.items():
            if self.is_compatible(obj):
                yield obj

    def get_default_figure(self, silent=False):
        if not silent:
            print("Plotly does not have a default figure. Please specify a figure to publish.", file=sys.stderr)

        return None

    def get_title(self, fig):
        title_text = None
        try:
            title = fig.layout.title
            if isinstance(title, go.layout.Title):
                title_text = title.text
            elif isinstance(title, str):
                title_text = title
        except Exception:
            title_text = None

        return title_text

    def figure_to_bytes(self, fig, fmt):
        return fig.to_image(format=fmt)

    def close(self, fig):
        pass

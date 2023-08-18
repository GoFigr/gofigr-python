"""\
Copyright (c) 2023, Flagstaff Solutions, LLC
All rights reserved.

"""
import inspect
import sys

import plotly.graph_objects as go
from gofigr.backends import GoFigrBackend, get_all_function_arguments


class PlotlyBackend(GoFigrBackend):
    """Plotly backend for GoFigr"""
    def is_compatible(self, fig):
        return isinstance(fig, go.Figure)

    def is_interactive(self, fig):
        return True

    def find_figures(self, shell, data):
        frames = inspect.stack()
        # Make sure there's an actual figure being published, as opposed to Plotly initialization scripts
        if 'application/vnd.plotly.v1+json' not in data.keys():
            return

        # Walk through the stack in *reverse* order (from top to bottom), to find the first call
        # in case display() was called recursively
        for f in reversed(frames):
            if f.function == "show" and "plotly" in f.filename:
                for arg_value in get_all_function_arguments(f):
                    if self.is_compatible(arg_value):
                        yield arg_value

                break

    # pylint: disable=useless-return
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
        except Exception:  # pylint: disable=broad-exception-caught
            title_text = None

        return title_text

    def figure_to_bytes(self, fig, fmt, params):
        return fig.to_image(format=fmt, **params)

    def figure_to_html(self, fig):
        return fig.to_html(include_plotlyjs='cdn')

    def add_interactive_watermark(self, fig, rev, watermark):
        # pylint: disable=use-dict-literal
        orig_height = getattr(fig.layout, "height")
        if orig_height is None:
            orig_height = 450  # Plotly default

        margin = 100
        new_height = 2 * margin + orig_height

        wfig = go.Figure(fig)
        wfig.update_layout(margin=dict(l=0, r=0, t=margin, b=margin))
        wfig.update_layout(height=new_height)

        wfig.add_annotation(dict(font=dict(color='black', size=15),
                                 x=0,
                                 y=-margin / orig_height,
                                 showarrow=False,
                                 text=f"<a href='{rev.revision_url}'>{rev.revision_url}</a>",
                                 textangle=0,
                                 xanchor='left',
                                 xref="paper",
                                 yref="paper"))

        return wfig

    def close(self, fig):
        pass

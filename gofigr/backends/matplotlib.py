"""\
Copyright (c) 2023, Flagstaff Solutions, LLC
All rights reserved.

"""
import inspect
import io

import matplotlib
import matplotlib.pyplot as plt

from gofigr.backends import GoFigrBackend, get_all_function_arguments


class SuppressPltWarnings:
    """Temporarily suppresses matplotlib warnings."""

    def __init__(self):
        self.plt_log = None
        self.log_level = None

    def __enter__(self):
        # Save initial log level
        self.plt_log = getattr(plt, "_log")
        self.log_level = getattr(self.plt_log, "level") if self.plt_log is not None else None
        plt.set_loglevel("error")

    def __exit__(self, exc_type, exc_val, exc_tb):
        # Restore log level
        if self.plt_log is not None and self.log_level is not None:
            self.plt_log.setLevel(self.log_level)


class MatplotlibBackend(GoFigrBackend):
    """\
    MatplotLib backend for GoFigr.

    """
    def get_backend_name(self):
        return "matplotlib"

    def is_compatible(self, fig):
        return isinstance(fig, matplotlib.figure.Figure)

    def is_interactive(self, fig):
        return False

    def find_figures(self, shell, data):
        frames = inspect.stack()
        # Walk through the stack in *reverse* order (from top to bottom), to find the first call
        # in case display() was called recursively
        for f in reversed(frames):
            if f.function == "display" and ("IPython" in f.filename or 'matplot' in f.filename):
                for arg_value in get_all_function_arguments(f):
                    if self.is_compatible(arg_value):
                        yield arg_value

                break

    def get_default_figure(self, silent=False):
        return plt.gcf()

    @staticmethod
    def title_to_string(title):
        """Extracts the title as a string from a title-like object (e.g. Text)"""
        if title is None:
            return None
        elif isinstance(title, matplotlib.text.Text):
            return title.get_text()
        elif isinstance(title, str):
            return title
        else:
            return None

    def get_title(self, fig):
        suptitle = MatplotlibBackend.title_to_string(getattr(fig, "_suptitle", ""))
        title = MatplotlibBackend.title_to_string(fig.axes[0].get_title() if len(fig.axes) > 0 else None)
        if suptitle is not None and suptitle.strip() != "":
            return suptitle
        elif title is not None and title.strip() != "":
            return title
        else:
            return None

    def figure_to_bytes(self, fig, fmt, params):
        with SuppressPltWarnings():
            bio = io.BytesIO()
            fig.savefig(bio, format=fmt, **params)
            bio.seek(0)
            return bio.read()

    def close(self, fig):
        plt.close(fig)

    def get_supported_image_formats(self):
        return ["png", "eps", "pdf", "jpeg", "jpg", "svg", "tiff"]

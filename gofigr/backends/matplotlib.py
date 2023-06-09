"""\
Copyright (c) 2023, Flagstaff Solutions, LLC
All rights reserved.

"""
import io

import matplotlib
import matplotlib.pyplot as plt

from gofigr.backends import GoFigrBackend


class MatplotlibBackend(GoFigrBackend):
    """\
    MatplotLib backend for GoFigr.

    """
    def is_compatible(self, fig):
        return isinstance(fig, matplotlib.figure.Figure)

    def is_interactive(self, fig):
        return False

    def find_figures(self, shell):
        for num in plt.get_fignums():
            yield plt.figure(num)

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
        bio = io.BytesIO()
        fig.savefig(bio, format=fmt, **params)

        bio.seek(0)
        return bio.read()

    def close(self, fig):
        plt.close(fig)

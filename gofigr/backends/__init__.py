"""\
Copyright (c) 2023, Flagstaff Solutions, LLC
All rights reserved.

"""
import inspect
from abc import ABC


def get_all_function_arguments(frame):
    """Iterates over all function arguments, including *args and **kwargs"""
    arg_values = inspect.getargvalues(frame[0])

    # Positional arguments
    for arg_name in arg_values.args:
        arg_value = arg_values.locals[arg_name]
        yield arg_value

    # Varargs
    if arg_values.varargs:
        for arg_value in arg_values.locals[arg_values.varargs]:
            yield arg_value

    # Kwargs
    if arg_values.keywords:
        for arg_value in arg_values.locals[arg_values.keywords].values():
            yield arg_value

class GoFigrBackend(ABC):
    """Base class for figure backends, e.g. matplotlib or plotly"""
    def is_compatible(self, fig):
        """Returns True if this backend is compatible with a figure"""
        raise NotImplementedError

    def is_interactive(self, fig):
        """Returns True if the figure supports interactive (HTML) output"""
        raise NotImplementedError

    def is_static(self, fig):
        """Returns True if the figure is static (e.g. an image)"""
        return not self.is_interactive(fig)

    def find_figures(self, shell, data):
        """\
        Finds all figures compatible with this backend in the current environment.

        :param shell: IPython shell
        :return: iterator over available figures
        """
        raise NotImplementedError

    def get_default_figure(self, silent=False):
        """"\
        Returns the default/current figure, e.g. plt.gcf() for matplotlib

        :param silent: if True, will suppress warnings/errors if default figure is unavailable
        """
        raise NotImplementedError

    def get_title(self, fig):
        """\
        Extracts figure title

        :param fig: figure to extract title from
        :return: figure title, or None if not available
        """
        raise NotImplementedError

    def figure_to_bytes(self, fig, fmt, params):
        """\
        Given a figure and an image format, converts the figure to binary representation in that format.

        :param fig: figure object
        :param fmt: format, e.g. png
        :param params: backend-specific parameters
        :return: bytes

        """
        raise NotImplementedError

    def figure_to_html(self, fig):
        """\
        Converts a figure to interactive HTML (if supported by the backend)

        :param fig: figure to convert to HTML
        :return: figure as HTML string

        """
        raise NotImplementedError

    def add_interactive_watermark(self, fig, rev, watermark):
        """\
        Adds watermark to a figure using the backend's native objects (if supported by the backend)

        :param fig: figure to watermark
        :param rev: FigureRevision object
        :param watermark: DefaultWatermark instance
        :return: modified figure

        """
        raise NotImplementedError

    def close(self, fig):
        """\
        Closes a figure and prevents it from being displayed.
        :param fig: figure to close
        :return: None
        """
        raise NotImplementedError


def get_backend(figure, backends):
    """\
    Gets the backend compatible with a figure

    :param figure: figure to find a backend for
    :param backends: list of backends to search
    :return: GoFigr backend compatible with the figure, or ValueError if none are compatible.

    """
    for back in backends:
        if back.is_compatible(figure):
            return back

    raise ValueError(f"Could not find a backend compatible with {figure}. "
                     f"Checked: {', '.join([str(back) for back in backends])}")

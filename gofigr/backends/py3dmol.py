"""\
Copyright (c) 2023, Flagstaff Solutions, LLC
All rights reserved.

"""
import inspect
import os
import re
import sys
import tempfile

import py3Dmol
from html2image import Html2Image

from gofigr.backends import GoFigrBackend, get_all_function_arguments


class WatermarkedView(py3Dmol.view):
    """Overrides py3Dmol.view to include a GoFigr watermark"""
    def __init__(self, wrapped_obj, extra_html):
        super().__init__()
        self.wrapped_obj = wrapped_obj
        self.extra_html = extra_html

    def _make_html(self):
        # pylint: disable=protected-access
        return self.wrapped_obj._make_html() + self.extra_html


class Py3DmolBackend(GoFigrBackend):
    """Plotly backend for GoFigr"""
    def __init__(self, *args, debug=False, image_size=(1920, 1080),
                 disable_logging=True, **kwargs):
        super().__init__(*args, **kwargs)
        self.image_size = image_size
        self.hti = Html2Image(size=image_size, disable_logging=disable_logging)
        self.debug = debug

    def get_backend_name(self):
        return "py3dmol"

    def is_compatible(self, fig):
        return isinstance(fig, py3Dmol.view)

    def is_interactive(self, fig):
        return True

    def _debug(self, text):
        if self.debug:
            print(text)

    def _infer_size(self, html):
        m = re.search(r'position: relative; width: (\d+)px; height: (\d+)px', html)
        if m is None:
            return self.image_size
        else:
            return int(m.group(1)), int(m.group(2))

    def find_figures(self, shell, data):
        self._debug("Looking for py3dmol figures...")
        self._debug(f"Available MIME types: {data.keys()}")

        frames = inspect.stack()
        # Make sure there's an actual figure being published, as opposed to Plotly initialization scripts
        if not any('3dmoljs' in x for x in data.keys()):
            self._debug("Could not locate 3dmoljs MIME type. Stopping search early.")
            return
        else:
            self._debug("3dmoljs MIME found")

        # Walk through the stack in *reverse* order (from top to bottom), to find the first call
        # in case display() was called recursively
        for idx, f in enumerate(reversed(frames)):
            self._debug(f"Frame {idx + 1}: function={f.function} file={f.filename}")
            if ("show" in f.function or "repr_html" in f.function) and "py3dmol" in f.filename.lower():
                self._debug("Found make_html call")
                for arg_idx, arg_value in enumerate(get_all_function_arguments(f)):
                    self._debug(f"Inspecting argument {arg_idx + 1}: "
                                f"{arg_value.__class__ if not arg_value is None else None}")
                    if self.is_compatible(arg_value):
                        self._debug("Argument is compatible with GoFigr")
                        yield arg_value
                    else:
                        self._debug("Argument not compatible.")

                break

    # pylint: disable=useless-return
    def get_default_figure(self, silent=False):
        if not silent:
            print("py3Dmol does not have a default figure. Please specify a figure to publish.", file=sys.stderr)

        return None

    def get_title(self, fig):
        title = getattr(fig, "title", None)
        if not isinstance(title, str):
            return None
        else:
            return title

    def figure_to_bytes(self, fig, fmt, params):
        if fmt == "png":
            with tempfile.NamedTemporaryFile(suffix=".png", dir=self.hti.output_path) as ntf:
                fig_html = self.figure_to_html(fig)
                width, height = self._infer_size(fig_html)
                self.hti.screenshot(html_str=fig_html, save_as=os.path.basename(ntf.name),
                                    size=(width, height))

                with open(ntf.name, 'rb') as f:
                    return f.read()

        raise ValueError(f"Py3Dmol does not support {fmt.upper()}")

    def figure_to_html(self, fig):
        return fig._make_html()  # pylint: disable=protected-access

    def add_interactive_watermark(self, fig, rev, watermark):
        watermark_html = f"<div><a href='{rev.revision_url}'>{rev.revision_url}</a></div>"
        return WatermarkedView(fig, watermark_html)

    def get_supported_image_formats(self):
        return ["png"]

    def close(self, fig):
        pass

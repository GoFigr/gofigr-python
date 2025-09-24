import asyncio
import io
import logging
import os
import uuid
from datetime import timedelta, datetime

import time

import PIL
import nest_asyncio
from ipywidgets import widgets
from ipywidgets.comm import create_comm

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from gofigr.annotators import GitAnnotator, NotebookMetadataAnnotator, NOTEBOOK_NAME
from gofigr.backends import get_backend
from gofigr.backends.matplotlib import MatplotlibBackend
from gofigr.backends.plotly import PlotlyBackend
from gofigr.backends.plotnine import PlotnineBackend
from gofigr.utils import read_resource_b64, read_resource_binary

try:
    from IPython.core.display_functions import display
except ModuleNotFoundError:
    from IPython.core.display import display


from gofigr import GoFigr, NotebookName
from gofigr.jupyter import _GoFigrExtension
from gofigr.publisher import _make_backend, DEFAULT_BACKENDS, _mark_as_published, \
    is_published, is_suppressed, PLOTNINE_PRESENT
from gofigr.watermarks import DefaultWatermark, _qr_to_image, add_margins, stack_horizontally, stack_vertically
from gofigr.widget import LiteStartupWidget

_GF_EXTENSION = None

def get_extension():
    """Returns the GoFigr Jupyter extension instance"""
    return _GF_EXTENSION


class _LiteGoFigrExtension(_GoFigrExtension):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, auto_publish=True, **kwargs)
        self.comm_data = None
        self.startup_widget = widgets.Output()
        self.publisher = LitePublisher()

    def is_ready(self):
        return True

    def post_run_cell(self, result):
        self.cell = result.info


def gofigr_comm_handler(msg):
    ext = get_extension()
    first_data = ext.comm_data is None
    ext.comm_data = msg['content']['data']
    if first_data:
        with ext.startup_widget:
            LiteStartupWidget(get_extension()).show()

def _requeue(ip, digest, item):
    ip.kernel.session.digest_history = [x for x in ip.kernel.session.digest_history if x.decode('ascii') != digest.decode('ascii')]
    ip.kernel.msg_queue.put(item)


def load_ipython_extension(ip):
    """\
    Loads the "lite" Jupyter extension. The lite extension provides flexible
    figure watermarking but works offline and doesn't publish anything to
    GoFigr.io.

    :param ip: IPython shell
    :return: None

    """
    nest_asyncio.apply()

    global _GF_EXTENSION
    if _GF_EXTENSION is not None:
        _GF_EXTENSION.unregister()

    ext = _LiteGoFigrExtension(ip)
    ext.register_hooks()
    _GF_EXTENSION = ext

    ip.user_ns["get_extension"] = get_extension
    ip.user_ns["publish"] = publish

    display(ext.startup_widget)

    args = dict(target_name='gofigr',
                data={'state': "open"},
                metadata={})

    my_comm = create_comm(**args)
    my_comm.on_msg(gofigr_comm_handler)

    # load_ipython_extension is running within the same event queue as Comms,
    # so the comm will not be processed until much later (in some cases this can be after the whole
    # notebook has finished executing (!)).
    #
    # That's too late to be useful, so we manually process the event queue message here.
    logging.debug("Waiting for comm message...")

    start_time = datetime.now()
    seen_ids = set()
    while datetime.now() - start_time < timedelta(seconds=5):
        try:
            item = asyncio.run(ip.kernel.msg_queue.get(timeout=timedelta(seconds=1)))

            _, _, args = item
            idents, msg = ip.kernel.session.feed_identities(*args, copy=False)
            digest = msg[0].bytes

            msg = ip.kernel.session.deserialize(msg, content=True, copy=False)

            if digest in seen_ids:
                logging.debug("Already seen digest %s, re-queuing and waiting", digest)
                _requeue(ip, digest, item)
                asyncio.run(asyncio.sleep(0.5))
                continue

            seen_ids.add(digest)

            if msg['msg_type'] == 'comm_msg' and msg['content']['comm_id'] == my_comm.comm_id:
                gofigr_comm_handler(msg)
                break
            else:
                # Re-queuing the same message will throw an exception due to a duplicate digest, so we modify it slightly
                _requeue(ip, digest, item)

        except TimeoutError:
            logging.debug("Timeout. Waiting...")
            asyncio.run(asyncio.sleep(0.5))


class LiteClient(GoFigr):
    def __init__(self, *args, **kwargs):
        super().__init__(url=None, authenticate=False, *args, **kwargs)

    def _unsupported(self):
        raise ValueError("GoFigr Lite is local-only.")

    def _request(self, *args, **kwargs):
        self._unsupported()

    @property
    def sync(self):
        raise ValueError("GoFigr Lite is local-only. Asset sync is not supported.")


class LitePlotlyBackend(PlotlyBackend):
    """Plotly backend for GoFigr"""
    def get_backend_name(self):
        return "plotly_lite"

    def add_interactive_watermark(self, fig, rev, watermark):
        # Create subplots with 1 row and 2 columns,
        # and define the specs for a graph and a table
        if not isinstance(watermark, LiteWatermark):
            return fig

        orig_height = getattr(fig.layout, "height")
        if orig_height is None:
            orig_height = 450

        key_value_pairs = watermark.get_table(rev)
        table_height = 40 * len(key_value_pairs)
        total_height = orig_height + table_height

        # Define the subplot grid with three distinct areas
        specs = [
            [{'type': 'xy', 'colspan': 2}, None],  # Top row for the main graph
            [{'type': 'xy'}, {'type': 'table'}]  # Bottom row for the image and table
        ]

        new_fig = make_subplots(
            rows=2,
            cols=2,
            shared_xaxes=False,
            vertical_spacing=0.1,
            row_heights=[orig_height / total_height, 1.0 - orig_height / total_height],
            column_widths=[0.1, 0.9],  # Allocate more space to the table
            specs=specs
        )

        # Add all traces from the original figure to the top subplot
        for trace in fig.data:
            new_fig.add_trace(trace, row=1, col=1)

        # Add the GoFigr.io logo using add_layout_image
        logo_b64 = read_resource_b64("gofigr.resources", "logo_large.png")

        new_fig.add_layout_image(
            dict(
                source=f"data:image;base64,{logo_b64}",
                xref="paper",  # Anchor the image to the second subplot's x-axis
                yref="paper",  # Anchor the image to the second subplot's y-axis
                x=0.0,
                y=0.0,
                xanchor="left",
                yanchor="bottom",
                sizex=0.1,
                sizey=1.0 - orig_height / total_height,
                layer="below",
            )
        )

        # Make the subplot axes for the image invisible
        #new_fig.update_xaxes(visible=False, row=2, col=1)
        #new_fig.update_yaxes(visible=False, row=2, col=1)

        # Create the table
        header_values = ['', '']
        cell_values = [
            list(key_value_pairs.keys()),
            list(key_value_pairs.values())
        ]

        table = go.Table(
            header=dict(values=header_values, align='left', height=0),
            cells=dict(values=cell_values, align='left')
        )

        # Add the table to the bottom-right subplot
        new_fig.add_trace(table, row=2, col=2)

        # Update the overall layout
        new_fig.update_layout(
            title=fig.layout.title,
            height=orig_height + table_height
        )

        return new_fig



class LiteWatermark(DefaultWatermark):
    def get_table(self, revision):
        GitAnnotator().annotate(revision)
        NotebookMetadataAnnotator().annotate(revision, sync=False)

        git_link = revision.metadata.get('git', {}).get('commit_link', None)
        git_hash = revision.metadata.get('git', {}).get('hash', None)
        git_link = git_link or "No git link available"

        notebook_name = revision.metadata.get(NOTEBOOK_NAME, "N/A")

        return{"User": str(os.getlogin()),
               "Notebook": notebook_name,
               "Commit": git_hash,
               "Date": str(datetime.now()),
               "Git Link": git_link}

    def get_watermark(self, revision):
        """\
        Generates just the watermark for a revision.

        :param revision: FigureRevision
        :return: PIL.Image

        """
        data =  self.get_table(revision)
        table = [(f'{k}: ', v) for k, v in data.items() if k != "Git Link"]

        identifier_img = self.draw_table(table)
        git_link = data.get("Git Link", None)

        qr_img = None
        if self.show_qr_code and git_link:
            qr_img = _qr_to_image(git_link, scale=self.qr_scale,
                                  module_color=self.qr_foreground,
                                  background=self.qr_background)
            qr_img = add_margins(qr_img, self.margin_px)

        logo = PIL.Image.open(io.BytesIO(read_resource_binary("gofigr.resources", "logo_large.png")))
        logo_size = identifier_img.size[1]
        if qr_img and qr_img.size[1] > logo_size:
            logo_size = qr_img.size[1]

        logo.thumbnail((logo_size, logo_size))
        identifier_img = stack_horizontally(logo, identifier_img)

        return stack_horizontally(identifier_img, qr_img)


DEFAULT_LITE_BACKENDS = (MatplotlibBackend, LitePlotlyBackend)

if PLOTNINE_PRESENT:
    # pylint: disable=possibly-used-before-assignment
    DEFAULT_LITE_BACKENDS = (PlotnineBackend,) + DEFAULT_LITE_BACKENDS


class LitePublisher:
    """\
    "Lite" publisher: adds annotations to figures but doesn't publish anything to GoFigr.io.
    """
    # pylint: disable=too-many-arguments
    def __init__(self,
                 backends=None,
                 watermark=None,
                 show_watermark=True,
                 clear=False,
                 widget_class=None,
                 default_metadata=None):
        self.gf = LiteClient()
        self.watermark = watermark or LiteWatermark()
        self.show_watermark = show_watermark
        self.backends = [_make_backend(bck) for bck in (backends or DEFAULT_LITE_BACKENDS)]
        self.clear = clear
        self.widget_class = widget_class
        self.default_metadata = default_metadata or {}

    def auto_publish_hook(self, extension, data, suppress_display=None):
        """\
        Hook for automatically annotating figures.

        :param extension: GoFigrExtension instance
        :param data: Dictionary of mime formats.
        :param suppress_display: if used in an auto-publish hook, this will contain a callable which will
               suppress the display of this figure using the native IPython backend.

        :return: None
        """
        for backend in self.backends:
            compatible_figures = list(backend.find_figures(extension.shell, data))
            for fig in compatible_figures:
                if not is_published(fig) and not is_suppressed(fig):
                    self.publish(fig=fig, backend=backend, suppress_display=suppress_display)

            if len(compatible_figures) > 0:
                break

    def _apply_watermark(self, fig, rev, backend, image_options):
        """\
        Extracts ImageData in various formats.

        :param backend: backend to use
        :param fig: figure object
        :param rev: LiteRevision object
        :param image_options: backend-specific parameters
        :return: tuple of: list of ImageData objects, watermarked image to display

        """
        if image_options is None:
            image_options = {}

        if backend.is_interactive(fig):
            return backend.add_interactive_watermark(fig, rev, self.watermark)
        else:
            img = PIL.Image.open(io.BytesIO(backend.figure_to_bytes(fig, "png", image_options)))
            img.load()
            return self.watermark.apply(img, rev)

    def _infer_figure_and_backend(self, fig, backend):
        """\
        Given a figure and a backend where one of the values could be null, returns a complete set
        of a figure to publish and a matching backend.

        :param fig: figure to publish. None to publish the default for the backend
        :param backend: backend to use. If None, will infer from figure
        :return: tuple of figure and backend
        """
        if fig is None and backend is None:
            raise ValueError("You did not specify a figure to publish.")
        elif fig is not None and backend is not None:
            return fig, backend
        elif fig is None and backend is not None:
            fig = backend.get_default_figure()

            if fig is None:
                raise ValueError("You did not specify a figure to publish, and the backend does not have "
                                 "a default.")
        else:
            backend = get_backend(fig, self.backends)

        return fig, backend

    def publish(self, fig=None, metadata=None,
                backend=None, image_options=None, suppress_display=None):
        """\
        Publishes a revision to the server.

        :param fig: figure to publish. If None, we'll use plt.gcf()
        :param metadata: metadata (JSON) to attach to this revision
        :param backend: backend to use, e.g. MatplotlibBackend. If None it will be inferred automatically based on \
               figure type
        :param image_options: backend-specific params passed to backend.figure_to_bytes
        :param suppress_display: if used in an auto-publish hook, this will contain a callable which will
               suppress the display of this figure using the native IPython backend.

        :return: FigureRevision instance

        """
        # pylint: disable=too-many-branches, too-many-locals
        fig, backend = self._infer_figure_and_backend(fig, backend)

        combined_meta = self.default_metadata if self.default_metadata is not None else {}
        if metadata is not None:
            combined_meta.update(metadata)

        rev = self.gf.Revision(figure=None, metadata=combined_meta, backend=backend)

        image_to_display = self._apply_watermark(fig, rev, backend, image_options)

        if image_to_display is not None:
            display(image_to_display)

            if suppress_display is not None:
                suppress_display()

        _mark_as_published(fig)

        if self.clear and self.show_watermark:
            backend.close(fig)

        if self.widget_class is not None:
            self.widget_class(rev).show()

        return rev


def publish(fig=None, backend=None, **kwargs):
    """\
    Publishes a figure. See :func:`gofigr.lite.LitePublisher.publish` for a list of arguments. If figure and backend
    are both None, will publish default figures across all available backends.

    :param fig: figure to publish
    :param backend: backend to use
    :param kwargs:
    :return:

    """
    ext = get_extension()

    if fig is None and backend is None:
        # If no figure and no backend supplied, publish default figures across all available backends
        for available_backend in ext.publisher.backends:
            fig = available_backend.get_default_figure(silent=True)
            if fig is not None:
                return ext.publisher.publish(fig=fig, backend=available_backend, **kwargs)

        return None
    else:
        return ext.publisher.publish(fig=fig, backend=backend, **kwargs)
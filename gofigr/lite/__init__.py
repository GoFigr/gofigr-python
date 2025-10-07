"""\
Implements a limited fully-offline mode for GoFigr.

Copyright (c) 2023-2025, Flagstaff Solutions, LLC
All rights reserved.

"""
# pylint: disable=use-dict-literal, ungrouped-imports

import asyncio
import io
import logging
import os
import sys
from collections import namedtuple
from datetime import timedelta, datetime

import PIL
import nest_asyncio
import numpy as np
from IPython import get_ipython
from ipywidgets import widgets
from ipywidgets.comm import create_comm

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from gofigr import GoFigr
from gofigr.annotators import GitAnnotator, NotebookMetadataAnnotator, NOTEBOOK_NAME
from gofigr.backends.matplotlib import MatplotlibBackend
from gofigr.backends.plotly import PlotlyBackend
from gofigr.trap import SuppressDisplayTrap
from gofigr.utils import read_resource_b64, read_resource_binary
from gofigr.jupyter import _GoFigrExtension, _base_publish
from gofigr.publisher import _make_backend, _mark_as_published, \
    is_published, is_suppressed, suppress, infer_figure_and_backend
from gofigr.watermarks import DefaultWatermark, _qr_to_image, add_margins, stack_horizontally
from gofigr.widget import LiteStartupWidget

try:
    from IPython.core.display_functions import display
except ModuleNotFoundError:
    from IPython.core.display import display


PLOTNINE_PRESENT = False
try:
    import plotnine # pylint: disable=unused-import
    from gofigr.backends.plotnine import PlotnineBackend
    PLOTNINE_PRESENT = True
except ModuleNotFoundError:
    pass


logger = logging.getLogger(__name__)


EXTENSION_NAME = "_GF_EXTENSION_LITE"


def get_extension():
    """Returns the GoFigr Jupyter extension instance"""
    return get_ipython().user_ns.get(EXTENSION_NAME)


class _LiteGoFigrExtension(_GoFigrExtension):
    """Implementation of the GoFigr Jupyter extension for the "lite" (offline) backend."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, auto_publish=True, **kwargs)
        self.comm_data = None
        self.startup_widget = widgets.Output()
        self.publisher = LitePublisher()

    @property
    def is_ready(self):
        return True

    def post_run_cell(self, result):
        self.cell = result.info


def _gofigr_comm_handler(msg):
    ext = get_extension()
    first_data = ext.comm_data is None
    ext.comm_data = msg['content']['data']
    if first_data:
        with ext.startup_widget:
            LiteStartupWidget(get_extension()).show()


def _requeue(ip, digest, item):
    ip.kernel.session.digest_history = [x for x in ip.kernel.session.digest_history
                                        if x.decode('ascii') != digest.decode('ascii')]
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

    ext = get_extension()

    if ext is not None:
        ext.unregister()

    ext = _LiteGoFigrExtension(ip)
    ext.register_hooks()
    ip.user_ns[EXTENSION_NAME] = ext
    ip.user_ns["get_extension"] = get_extension
    ip.user_ns["publish"] = publish
    ip.user_ns["suppress"] = suppress

    display(ext.startup_widget)

    my_comm = create_comm(target_name='gofigr', data={'state': "open"}, metadata={})
    my_comm.on_msg(_gofigr_comm_handler)

    # load_ipython_extension is running within the same event queue as Comms,
    # so the comm will not be processed until much later (in some cases this can be after the whole
    # notebook has finished executing (!)).
    #
    # That's too late to be useful, so we manually process the event queue message here.
    logger.debug("Waiting for comm message...")

    start_time = datetime.now()
    queue_copy = []
    comm_received = False
    while not comm_received and datetime.now() - start_time < timedelta(seconds=5):
        try:
            item = asyncio.run(ip.kernel.msg_queue.get(timeout=timedelta(seconds=1)))

            _, _, args = item
            _, msg = ip.kernel.session.feed_identities(*args, copy=False)
            digest = msg[0].bytes

            msg = ip.kernel.session.deserialize(msg, content=True, copy=False)

            if msg['msg_type'] == 'comm_msg' and msg['content']['comm_id'] == my_comm.comm_id:
                # This is our message!
                _gofigr_comm_handler(msg)
                comm_received = True

                # It's important to keep going until we exhaust all messages. Otherwise the previous messages
                # will be appended out-of-order.

            queue_copy.append((digest, item))

        except TimeoutError:
            if comm_received:  # no more messages and comm-received: we're done
                break
            else:
                logger.debug("Timeout. Waiting...")  # no more messages and still no comm. Wait.
                asyncio.run(asyncio.sleep(0.5))

    # Restore the queue
    for digest, item in queue_copy:
        _requeue(ip, digest, item)


class LiteClient(GoFigr):
    """
    A specialized implementation of the GoFigr class designed for local-only usage.

    LiteClient is a restricted version of the GoFigr client. It is intended for environments
    where local-only functionality is required, eliminating any backend interaction or
    synchronization capabilities. This class disables remote requests and syncing, ensuring
    that all functionality remains self-contained and isolated.

    :param url: Always set to None as LiteClient does not interact with a remote server.
    :param authenticate: Always set to False since authentication is not required
        for local-only operation.

    """

    def __init__(self, *args, **kwargs):
        super().__init__(url=None, authenticate=False, *args, **kwargs)

    def _unsupported(self):
        raise ValueError("GoFigr Lite is local-only.")

    def _request(self, *args, **kwargs):  # pylint: disable=unused-argument
        self._unsupported()

    @property
    def sync(self):
        raise ValueError("GoFigr Lite is local-only. Asset sync is not supported.")


class LitePlotlyBackend(PlotlyBackend):
    """Plotly backend for GoFigr"""
    def get_backend_name(self):
        return "plotly_lite"

    def add_interactive_watermark(self, fig, rev, watermark):
        # pylint: disable=too-many-locals

        # isinstance doesn't work if the extension is reloaded because it re-loads class definitions.
        # So we rely on duck typing as a workaround.
        if not hasattr(watermark, "get_table"):
            logger.debug(f"Skipping watermarking because it's not a LiteWatermark instance: {watermark}")
            return fig

        orig_height = getattr(fig.layout, "height")
        if orig_height is None:
            orig_height = 450

        orig_width = getattr(fig.layout, "width")
        if orig_width is None:
            orig_width = 700

        logo_width =  np.clip(0.1 * orig_width, 70, 200)

        logo_height = logo_width

        key_value_pairs = watermark.get_table(rev)
        table_height = 40 * (len(key_value_pairs) + 1)
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
            column_widths=[logo_width / orig_width, 1.0 - logo_width / orig_width],  # Allocate more space to the table
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
                y=0.5 * (table_height - logo_height) / total_height,
                xanchor="left",
                yanchor="bottom",
                sizex=logo_width / orig_width,
                sizey=logo_height / orig_height,
                layer="below",
            )
        )

        # Make the subplot axes for the image invisible
        new_fig.update_xaxes(visible=False, row=2, col=1)
        new_fig.update_yaxes(visible=False, row=2, col=1)

        # Create the table
        header_values = ['Key', 'Value']
        cell_values = [
            list(key_value_pairs.keys()),
            list(key_value_pairs.values())
        ]

        table = go.Table(
            columnwidth=[100, 400],
            header=dict(values=header_values, align='left'),
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
    """
    Represents a specialized watermark generator extending DefaultWatermark.

    This class is designed to create lightweight watermarks for notebook figures
    with associated Git metadata and other contextual details. It provides custom
    methods to generate tables and optional QR codes with Git commit information.
    The generated watermark includes the user, notebook name, commit hash, and
    current date.

    :ivar show_qr_code: Flag indicating whether QR code generation is enabled.
    :type show_qr_code: bool
    :ivar qr_scale: Scale factor for QR code size.
    :type qr_scale: int
    :ivar qr_foreground: Foreground color of the QR code.
    :type qr_foreground: str
    :ivar qr_background: Background color of the QR code.
    :type qr_background: str
    :ivar margin_px: Pixel margin around the QR code.
    :type margin_px: int
    """

    def get_table(self, revision):
        """
        Retrieve a dictionary representing metadata information about a notebook revision.

        The method applies a series of annotators to enrich the given revision with
        additional metadata and then constructs a dictionary containing details such as
        the logged-in user, notebook name, commit details, and a timestamp of the operation.
        If certain metadata fields are not available, fallback default values are used.

        :param revision: The revision object whose metadata is to be processed.
            Must be annotated with `GitAnnotator` and `NotebookMetadataAnnotator`
            before metadata extraction.
        :type revision: Revision
        :return: A dictionary containing metadata details including user, notebook name,
            commit hash, timestamp, and a link to the Git commit. Defaults to placeholder
            values if the data is unavailable in the revision.
        :rtype: dict

        """
        GitAnnotator().annotate(revision)
        NotebookMetadataAnnotator().annotate(revision, sync=False)

        git_link = revision.metadata.get('git', {}).get('commit_link', None)
        git_hash = revision.metadata.get('git', {}).get('hash', None)
        git_link = git_link or "No git link available"

        notebook_name = revision.metadata.get(NOTEBOOK_NAME, "N/A")

        data = {"User": str(os.getlogin()),
               "Notebook": notebook_name,
               "Commit": git_hash,
               "Date": str(datetime.now()),
               "Git Link": git_link}
        return {k: v for k, v in data.items() if v is not None}

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


_LoggedRevision = namedtuple("_LoggedRevision",
                             ["revision", "backend", "title", "displayed_image"])


class LitePublisher:
    """\
    "Lite" publisher: adds annotations to figures but doesn't publish anything to GoFigr.io.
    """
    # pylint: disable=too-many-arguments
    def __init__(self,
                 backends=None,
                 watermark=None,
                 show_watermark=True,
                 clear=True,
                 widget_class=None,
                 default_metadata=None,
                 log_revisions=False):
        self.gf = LiteClient()
        self.watermark = watermark or LiteWatermark()
        self.show_watermark = show_watermark
        self.backends = [_make_backend(bck) for bck in (backends or DEFAULT_LITE_BACKENDS)]
        self.clear = clear
        self.widget_class = widget_class
        self.default_metadata = default_metadata or {}
        self.revision_log = []
        self.log_revisions = log_revisions

    def auto_publish_hook(self, extension, data, suppress_display=None):
        """\
        Hook for automatically annotating figures.

        :param extension: GoFigrExtension instance
        :param data: Dictionary of mime formats.
        :param suppress_display: if used in an auto-publish hook, this will contain a callable which will
               suppress the display of this figure using the native IPython backend.

        :return: None
        """
        logger.debug("Running auto-publish hook")
        for backend in self.backends:
            logger.debug(f"Trying backend {backend}")
            compatible_figures = list(backend.find_figures(extension.shell, data))
            logger.debug(f"Found {len(compatible_figures)} figures")
            for fig in compatible_figures:
                logger.debug(f"Checking figure {fig}. Published: {is_published(fig)}. Suppressed: {is_suppressed(fig)}")
                if not is_published(fig) and not is_suppressed(fig):
                    logger.debug("Publishing...")
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

    def publish(self, fig=None, metadata=None,
                backend=None, image_options=None,
                suppress_display=None, **kwargs):
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
        if len(kwargs) > 0:
            print(f"GoFigr Lite does not support the following arguments: {', '.join(kwargs)}", file=sys.stderr)

        # pylint: disable=too-many-branches, too-many-locals
        fig, backend = infer_figure_and_backend(fig, backend, self.backends)

        combined_meta = dict(self.default_metadata) if self.default_metadata is not None else {}
        if metadata is not None:
            combined_meta.update(metadata)

        rev = self.gf.Revision(figure=None, metadata=combined_meta, backend=backend)  # pylint: disable=no-member

        logger.debug("Applying watermark to figure %s", fig)
        image_to_display = self._apply_watermark(fig, rev, backend, image_options)
        logger.debug("Watermark applied: %s", image_to_display)

        if image_to_display is not None:
            with SuppressDisplayTrap():
                logger.debug("Displaying watermarked figure")
                display(image_to_display)

            if suppress_display is not None:
                suppress_display()

        _mark_as_published(fig)

        if self.clear and self.show_watermark:
            backend.close(fig)

        if self.widget_class is not None:
            self.widget_class(rev).show()

        if self.log_revisions:
            self.revision_log.append(_LoggedRevision(rev, backend, backend.get_title(fig), image_to_display))

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
    return _base_publish(ext=get_extension(), fig=fig, backend=backend, **kwargs)

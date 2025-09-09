import io

import PIL
from ipykernel.comm import Comm

from gofigr.annotators import GitAnnotator

try:
    from IPython.core.display_functions import display
except ModuleNotFoundError:
    from IPython.core.display import display

from IPython.display import Javascript

from gofigr import MeasureExecution, gf_Revision, GoFigr
from gofigr.backends import get_backend
from gofigr.jupyter import _GoFigrExtension
from gofigr.publisher import _make_annotator, DEFAULT_ANNOTATORS, _make_backend, DEFAULT_BACKENDS, _mark_as_published, \
    is_published, is_suppressed
from gofigr.watermarks import DefaultWatermark, _qr_to_image, add_margins, stack_horizontally
from gofigr.widget import LiteStartupWidget

_GF_EXTENSION = None


def get_extension():
    """Returns the GoFigr Jupyter extension instance"""
    return _GF_EXTENSION


def load_ipython_extension(ip):
    """\
    Loads the "lite" Jupyter extension. The lite extension provides flexible
    figure watermarking but works offline and doesn't publish anything to
    GoFigr.io.

    :param ip: IPython shell
    :return: None

    """
    global _GF_EXTENSION
    if _GF_EXTENSION is not None:
        _GF_EXTENSION.unregister()

    _GF_EXTENSION = _GoFigrExtension(ip, offline=True, auto_publish=True)
    _GF_EXTENSION.publisher = LitePublisher()
    _GF_EXTENSION.register_hooks()

    ip.user_ns["get_extension"] = get_extension
    ip.user_ns["publish"] = publish

    if get_extension().is_ready:
        LiteStartupWidget(get_extension()).show()


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


class LiteWatermark(DefaultWatermark):
    def get_watermark(self, revision):
        """\
        Generates just the watermark for a revision.

        :param revision: FigureRevision
        :return: PIL.Image

        """
        GitAnnotator().annotate(revision)

        git_link = revision.metadata.get('git', {}).get('commit_link', None)

        identifier_text = git_link or 'No git link available'
        identifier_img = self.draw_identifier(identifier_text)

        qr_img = None
        if self.show_qr_code and git_link:
            qr_img = _qr_to_image(identifier_text, scale=self.qr_scale,
                                  module_color=self.qr_foreground,
                                  background=self.qr_background)
            qr_img = add_margins(qr_img, self.margin_px)

        return stack_horizontally(identifier_img, qr_img)


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
        self.backends = [_make_backend(bck) for bck in (backends or DEFAULT_BACKENDS)]
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
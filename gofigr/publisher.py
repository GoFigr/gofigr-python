"""\
Copyright (c) 2023-2025, Flagstaff Solutions, LLC
All rights reserved.

"""
# pylint: disable=protected-access, ungrouped-imports

import io
import os
import pickle
import sys

import PIL
from IPython.core.display_functions import display

from gofigr import GoFigr, MeasureExecution, NotebookName
from gofigr.annotators import CellIdAnnotator, SystemAnnotator, CellCodeAnnotator, \
    PipFreezeAnnotator, NotebookMetadataAnnotator, EnvironmentAnnotator, BackendAnnotator, HistoryAnnotator, \
    GitAnnotator, Annotator, ScriptAnnotator
from gofigr.backends import get_backend, GoFigrBackend
from gofigr.backends.matplotlib import MatplotlibBackend
from gofigr.backends.plotly import PlotlyBackend
from gofigr.watermarks import DefaultWatermark
from gofigr.widget import DetailedWidget

PY3DMOL_PRESENT = False
if sys.version_info >= (3, 8):
    try:
        import py3Dmol  # pylint: disable=unused-import
        from gofigr.backends.py3dmol import Py3DmolBackend
        PY3DMOL_PRESENT = True
    except ModuleNotFoundError:
        pass

PLOTNINE_PRESENT = False
try:
    import plotnine # pylint: disable=unused-import
    from gofigr.backends.plotnine import PlotnineBackend
    PLOTNINE_PRESENT = True
except ModuleNotFoundError:
    pass

DEFAULT_ANNOTATORS = (NotebookMetadataAnnotator, EnvironmentAnnotator, CellIdAnnotator, CellCodeAnnotator,
                      SystemAnnotator, PipFreezeAnnotator, BackendAnnotator, HistoryAnnotator,
                      GitAnnotator, ScriptAnnotator)
DEFAULT_BACKENDS = (MatplotlibBackend, PlotlyBackend)
if PY3DMOL_PRESENT:
    # pylint: disable=possibly-used-before-assignment
    DEFAULT_BACKENDS = DEFAULT_BACKENDS + (Py3DmolBackend,)

if PLOTNINE_PRESENT:
    # pylint: disable=possibly-used-before-assignment
    DEFAULT_BACKENDS = (PlotnineBackend,) + DEFAULT_BACKENDS


def _mark_as_published(fig):
    """Marks the figure as published so that it won't be re-published again."""
    fig._gf_is_published = True
    return fig


def suppress(fig):
    """Suppresses the figure from being auto-published. You can still publish it by calling publish()."""
    fig._gf_is_suppressed = True
    return fig


def is_suppressed(fig):
    """Determines if the figure is suppressed from publication"""
    return getattr(fig, "_gf_is_suppressed", False)


def is_published(fig):
    """Returns True iff the figure has already been published"""
    return getattr(fig, "_gf_is_published", False)


# pylint: disable=too-many-instance-attributes
class Publisher:
    """\
    Publishes revisions to the GoFigr server.
    """
    # pylint: disable=too-many-arguments
    def __init__(self,
                 gf=None,
                 workspace=None,
                 analysis=None,
                 annotators=None,
                 backends=None,
                 watermark=None,
                 show_watermark=True,
                 image_formats=("png", "eps", "svg"),
                 interactive=True,
                 default_metadata=None,
                 clear=False,
                 save_pickle=True,
                 widget_class=DetailedWidget):
        """

        :param gf: GoFigr instance
        :param annotators: revision annotators
        :param backends: figure backends, e.g. MatplotlibBackend
        :param watermark: watermark generator, e.g. QRWatermark()
        :param show_watermark: True to show watermarked figures instead of original.
        False to always display the unmodified figure. Default True.
        :param image_formats: image formats to save by default
        :param interactive: whether to publish figure HTML if available
        :param clear: whether to close the original figures after publication
        :param save_pickle: if True, will save the figure in pickle format in addition to any of the image formats
        :param widget_class: Widget type to show, e.g. DetailedWidget or CompactWidget. It will appear below the
        published figure

        """
        self.gf = gf or GoFigr()
        self.watermark = watermark or DefaultWatermark()
        self.show_watermark = show_watermark
        self.annotators = [_make_annotator(ann) for ann in (annotators or DEFAULT_ANNOTATORS)]
        self.backends = [_make_backend(bck) for bck in (backends or DEFAULT_BACKENDS)]
        self.image_formats = image_formats
        self.interactive = interactive
        self.clear = clear
        self.default_metadata = default_metadata
        self.save_pickle = save_pickle
        self.widget_class = widget_class

        self.workspace = self.gf.find_workspace(workspace).fetch()
        self.analysis = self.gf.find_analysis(self.workspace, analysis)

    def _check_analysis(self):
        if self.analysis is None:
            print("You did not specify an analysis to publish under. Please call "
                  "configure(...) and specify one. See "
                  "https://gofigr.io/docs/gofigr-python/latest/gofigr.html#gofigr.jupyter.configure.",
                  file=sys.stderr)
            return None
        elif isinstance(self.analysis, NotebookName):
            print("Your analysis is set to the name of this notebook, but the name could "
                  "not be inferred. Please call "
                  "configure(...) and specify the analysis manually. See "
                  "https://gofigr.io/docs/gofigr-python/latest/gofigr.html#gofigr.jupyter.configure.",
                  file=sys.stderr)
            return None
        else:
            return self.analysis

    def _resolve_target(self, fig, target, backend):
        analysis = self._check_analysis()
        if analysis is None:
            return None

        if target is None:
            # Try to get the figure's title
            fig_name = backend.get_title(fig)
            if fig_name is None:
                print("Your figure doesn't have a title and will be published as 'Anonymous Figure'. "
                      "To avoid this warning, set a figure title or manually call publish() with a target figure. "
                      "See https://gofigr.io/docs/gofigr-python/latest/start.html#publishing-your-first-figure for "
                      "an example.", file=sys.stderr)
                fig_name = "Anonymous Figure"

            sys.stdout.flush()
            return analysis.get_figure(fig_name, create=True)
        else:
            return self.gf.find_figure(analysis, target)

    def _get_pickle_data(self, gf, fig, revision, target):
        if not self.save_pickle:
            return []

        try:
            bio = io.BytesIO()
            pickle.dump(fig, bio)
            bio.seek(0)

            return [gf.FileData(name=f"{target.name}_rev_{revision.revision_index + 1}.pickle",
                                 data=bio.getvalue())]
        except Exception as e: # pylint: disable=broad-exception-caught
            print(f"WARNING: We could not obtain the figure in pickle format: {e}", file=sys.stderr)
            return []

    def _get_image_data(self, gf, backend, fig, rev, target, image_options):
        """\
        Extracts ImageData in various formats.

        :param gf: GoFigr instance
        :param backend: backend to use
        :param fig: figure object
        :param rev: gf.Revision object
        :param target: gf.Figure object
        :param image_options: backend-specific parameters
        :return: tuple of: list of ImageData objects, watermarked image to display

        """
        # pylint: disable=too-many-locals

        if image_options is None:
            image_options = {}

        image_to_display = None
        image_data = []
        for fmt in self.image_formats:
            if fmt.lower() not in backend.get_supported_image_formats():
                continue

            if fmt.lower() == "png":
                img = PIL.Image.open(io.BytesIO(backend.figure_to_bytes(fig, fmt, image_options)))
                img.load()
                watermarked_img = self.watermark.apply(img, rev)
            else:
                watermarked_img = None

            # First, save the image without the watermark
            try:
                image_data.append(gf.ImageData(name="figure",
                                               format=fmt,
                                               data=backend.figure_to_bytes(fig, fmt, image_options),
                                               is_watermarked=False))
            except Exception as e:  # pylint: disable=broad-exception-caught
                print(f"WARNING: We could not obtain the figure in {fmt.upper()} format: {e}", file=sys.stderr)
                continue

            # Now, save the watermarked version (if available)
            if watermarked_img is not None:
                bio = io.BytesIO()
                watermarked_img.save(bio, format=fmt)
                img_data = gf.ImageData(name="figure", format=fmt, data=bio.getvalue(),
                                        is_watermarked=True)
                image_data.append(img_data)

                if fmt.lower() == 'png':
                    image_to_display = img_data

        if self.interactive and backend.is_interactive(fig):
            image_data.append(gf.ImageData(name="figure", format="html",
                                           data=backend.figure_to_html(fig).encode('utf-8'),
                                           is_watermarked=False))

            wfig = backend.add_interactive_watermark(fig, rev, self.watermark)
            html_with_watermark = gf.ImageData(name="figure", format="html",
                                               data=backend.figure_to_html(wfig).encode('utf-8'),
                                               is_watermarked=True)
            image_data.append(html_with_watermark)
            image_to_display = wfig  # display the native Figure

        image_data.extend(self._get_pickle_data(gf, fig, rev, target))

        return image_data, image_to_display

    def annotate(self, rev, annotators=None):
        """
        Annotates a FigureRevision using self.annotators.
        :param rev: revision to annotate
        :param annotators: list of annotators to use. Defaults to self.annotators
        :return: annotated revision

        """
        for annotator in (annotators or self.annotators):
            with MeasureExecution(annotator.__class__.__name__):
                annotator.annotate(rev)

        # Add data annotations
        rev.assets = [self.gf.AssetLinkedToFigure(figure_revision=rev,
                                                  asset_revision=data_rev,
                                                  use_type="indirect") for data_rev in self.gf.sync.revisions]
        return rev

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

    def _prepare_files(self, gf, files):
        if not isinstance(files, dict):
            files = {os.path.basename(p): p for p in files}

        data = []
        for name, filelike in files.items():
            if isinstance(filelike, str): # path
                with open(filelike, 'rb') as f:
                    data.append(gf.FileData(data=f.read(), name=name, path=filelike))
            else:  # stream
                data.append(gf.FileData(data=filelike.read(), name=name, path=None))

        return data

    def publish(self, fig=None, target=None, dataframes=None, metadata=None,
                backend=None, image_options=None, suppress_display=None, files=None,
                annotators=None):
        """\
        Publishes a revision to the server.

        :param fig: figure to publish. If None, we'll use plt.gcf()
        :param target: Target figure to publish this revision under. Can be a gf.Figure instance, an API ID, \
        or a FindByName instance.
        :param dataframes: dictionary of dataframes to associate & publish with the figure
        :param metadata: metadata (JSON) to attach to this revision
        :param backend: backend to use, e.g. MatplotlibBackend. If None it will be inferred automatically based on \
        figure type
        :param image_options: backend-specific params passed to backend.figure_to_bytes
        :param suppress_display: if used in an auto-publish hook, this will contain a callable which will
        suppress the display of this figure using the native IPython backend.
        :param files: either (a) list of file paths or (b) dictionary of name to file path/file obj
        :param annotators: list of annotators to use. Defaults to self.annotators

        :return: FigureRevision instance

        """
        # pylint: disable=too-many-branches, too-many-locals
        fig, backend = self._infer_figure_and_backend(fig, backend)

        with MeasureExecution("Resolve target"):
            target = self._resolve_target(fig, target, backend)
            if getattr(target, 'revisions', None) is None:
                target.fetch()

        combined_meta = self.default_metadata if self.default_metadata is not None else {}
        if metadata is not None:
            combined_meta.update(metadata)

        with MeasureExecution("Bare revision"):
            # Create a bare revision first to get the API ID
            rev = self.gf.Revision(figure=target, metadata=combined_meta, backend=backend)
            target.revisions.create(rev)

        with MeasureExecution("Annotators"):
            # Annotate the revision
            self.annotate(rev, annotators=annotators)

        with MeasureExecution("Image data"):
            rev.image_data, image_to_display = self._get_image_data(self.gf, backend, fig, rev, target, image_options)

        if image_to_display is not None and self.show_watermark:
            if isinstance(image_to_display, self.gf.ImageData):
                display(image_to_display.image)
            else:
                display(image_to_display)

            if suppress_display is not None:
                suppress_display()

        if dataframes is not None:
            table_data = []
            for name, frame in dataframes.items():
                table_data.append(self.gf.TableData(name=name, dataframe=frame))

            rev.table_data = table_data

        if files is not None:
            rev.file_data = self._prepare_files(self.gf, files)

        with MeasureExecution("Final save"):
            rev.save(silent=True)

            # Calling .save() above will update internal properties based on the response from the server.
            # In our case, this will result in rev.figure becoming a shallow object with just the API ID. Here
            # we restore it from our cached copy, to avoid a separate API call.
            rev.figure = target

        _mark_as_published(fig)

        if self.clear and self.show_watermark:
            backend.close(fig)

        self.widget_class(rev).show()
        return rev


def _make_backend(backend):
    if isinstance(backend, GoFigrBackend):
        return backend
    else:
        return backend()


def _make_annotator(annotator):
    if isinstance(annotator, Annotator):
        return annotator
    else:
        return annotator()

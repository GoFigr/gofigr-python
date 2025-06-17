"""\
Copyright (c) 2023-2025, Flagstaff Solutions, LLC
All rights reserved.

"""
# pylint: disable=protected-access, ungrouped-imports

import io
import os
import pickle
import sys
from collections import namedtuple

import PIL
from IPython.core.display_functions import display

from gofigr import GoFigr, MeasureExecution, RevisionContext, UnauthorizedError
from gofigr.annotators import CellIdAnnotator, SystemAnnotator, CellCodeAnnotator, \
    PipFreezeAnnotator, NotebookMetadataAnnotator, EnvironmentAnnotator, BackendAnnotator, HistoryAnnotator, \
    GitAnnotator, Annotator
from gofigr.backends import get_backend, GoFigrBackend
from gofigr.backends.matplotlib import MatplotlibBackend
from gofigr.backends.plotly import PlotlyBackend
from gofigr.trap import SuppressDisplayTrap
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
                      GitAnnotator)
DEFAULT_BACKENDS = (MatplotlibBackend, PlotlyBackend)
if PY3DMOL_PRESENT:
    # pylint: disable=possibly-used-before-assignment
    DEFAULT_BACKENDS = DEFAULT_BACKENDS + (Py3DmolBackend,)

if PLOTNINE_PRESENT:
    # pylint: disable=possibly-used-before-assignment
    DEFAULT_BACKENDS = (PlotnineBackend,) + DEFAULT_BACKENDS


def find_workspace_by_name(gf, search):
    """\
    Finds a workspace by name.

    :param gf: GoFigr client
    :param search: FindByName instance
    :return: a Workspace object

    """
    matches = [wx for wx in gf.workspaces if wx.name == search.name]
    if len(matches) == 0:
        if search.create:
            wx = gf.Workspace(name=search.name, description=search.description)
            wx.create()
            print(f"Created a new workspace: {wx.api_id}")
            return wx
        else:
            raise RuntimeError(f'Could not find workspace named "{search.name}"')
    elif len(matches) > 1:
        raise RuntimeError(f'Multiple (n={len(matches)}) workspaces match name "{search.name}". '
                           f'Please use an API ID instead.')
    else:
        return matches[0]


class NotebookName:
    """\
    Used as argument to configure() to specify that we want the analysis name to default to the name of the notebook
    """
    def __repr__(self):
        return "NotebookName"


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


def _is_published(fig):
    """Returns True iff the figure has already been published"""
    return getattr(fig, "_gf_is_published", False)


def _resolve_workspace(gf, workspace):
    def _resolve():
        if workspace is None:
            if gf.primary_workspace is not None:
                return gf.primary_workspace
            elif len(gf.workspaces) == 1:  # this will happen if we're using a scoped API token
                return gf.workspaces[0]
            else:
                raise ValueError("Please specify a workspace")
        else:
            return parse_model_instance(gf.Workspace, workspace, lambda search: find_workspace_by_name(gf, search))

    worx = _resolve()
    with MeasureExecution("Fetch workspace"):
        try:
            worx.fetch()
        except UnauthorizedError as e:
            raise UnauthorizedError(f"Permission denied for workspace {workspace.api_id}. "
                                    f"Are you using a restricted API key?") from e
    return worx


def _resolve_analysis(gf, workspace, analysis):
    if analysis is None:
        raise ValueError("Please specify an analysis")
    elif isinstance(analysis, NotebookName) or str(analysis) == "NotebookName":  # str in case it's from config/env
        analysis = NotebookName()
    else:
        with MeasureExecution("Find analysis"):
            analysis = parse_model_instance(gf.Analysis, analysis,
                                            lambda search: workspace.get_analysis(name=search.name,
                                                                                  description=search.description,
                                                                                  create=search.create))

        with MeasureExecution("Fetch analysis"):
            analysis.fetch()

    return analysis


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
                 clear=True,
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
        :param clear: whether to close the original figures after publication. If False, Jupyter will display
        both the input figure and the watermarked output. Default behavior is to close figures.
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

        self.workspace = _resolve_workspace(self.gf, workspace)
        self.analysis = _resolve_analysis(self.gf, self.workspace, analysis)

    def auto_publish_hook(self, extension, data, suppress_display=None):
        """\
        Hook for automatically publishing figures without an explicit call to publish().

        :param extension: GoFigrExtension instance
        :param data: data being published. This will usually be a dictionary of mime formats.
        :param suppress_display: if used in an auto-publish hook, this will contain a callable which will
        suppress the display of this figure using the native IPython backend.

        :return: None
        """
        for backend in self.backends:
            compatible_figures = list(backend.find_figures(extension.shell, data))
            for fig in compatible_figures:
                if not _is_published(fig) and not is_suppressed(fig):
                    self.publish(fig=fig, backend=backend, suppress_display=suppress_display)

            if len(compatible_figures) > 0:
                break

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
            return parse_model_instance(self.gf.Figure,
                                        target,
                                        lambda search: analysis.get_figure(name=search.name,
                                                                           description=search.description,
                                                                           create=search.create))

    def _get_pickle_data(self, gf, fig):
        if not self.save_pickle:
            return []

        try:
            bio = io.BytesIO()
            pickle.dump(fig, bio)
            bio.seek(0)

            return [gf.ImageData(name="figure", format="pickle",
                                 data=bio.getvalue(),
                                 is_watermarked=False)]
        except Exception as e: # pylint: disable=broad-exception-caught
            print(f"WARNING: We could not obtain the figure in pickle format: {e}", file=sys.stderr)
            return []

    def _get_image_data(self, gf, backend, fig, rev, image_options):
        """\
        Extracts ImageData in various formats.

        :param gf: GoFigr instance
        :param backend: backend to use
        :param fig: figure object
        :param rev: Revision object
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

        image_data.extend(self._get_pickle_data(gf, fig))

        return image_data, image_to_display

    def annotate(self, rev):
        """
        Annotates a FigureRevision using self.annotators.
        :param rev: revision to annotate
        :return: annotated revision

        """
        for annotator in self.annotators:
            with MeasureExecution(annotator.__class__.__name__):
                annotator.annotate(rev)

        # Add data annotations
        rev.datasets = [self.gf.DatasetLinkedToFigure(figure_revision=rev,
                                                      dataset_revision=data_rev,
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
                backend=None, image_options=None, suppress_display=None, files=None):
        """\
        Publishes a revision to the server.

        :param fig: figure to publish. If None, we'll use plt.gcf()
        :param target: Target figure to publish this revision under. Can be a gf.Figure instance, an API ID, \
        or a FindByName instance.
        :param dataframes: dictionary of dataframes to associate & publish with the figure
        :param metadata: metadata (JSON) to attach to this revision
        usage this will cause Jupyter to print the whole object which we don't want.
        :param backend: backend to use, e.g. MatplotlibBackend. If None it will be inferred automatically based on \
        figure type
        :param image_options: backend-specific params passed to backend.figure_to_bytes
        :param suppress_display: if used in an auto-publish hook, this will contain a callable which will
        suppress the display of this figure using the native IPython backend.
        :param files: either (a) list of file paths or (b) dictionary of name to file path/file obj

        :return: FigureRevision instance

        """
        # pylint: disable=too-many-branches, too-many-locals
        from gofigr.jupyter import get_extension
        ext = get_extension()
        gf = self.gf if self.gf is not None else ext.gf
        fig, backend = self._infer_figure_and_backend(fig, backend)

        with MeasureExecution("Resolve target"):
            target = self._resolve_target(fig, target, backend)
            if getattr(target, 'revisions', None) is None:
                target.fetch()

        combined_meta = self.default_metadata if self.default_metadata is not None else {}
        if metadata is not None:
            combined_meta.update(metadata)

        context = RevisionContext(backend=backend, extension=ext)
        with MeasureExecution("Bare revision"):
            # Create a bare revision first to get the API ID
            rev = gf.Revision(figure=target, metadata=combined_meta)
            target.revisions.create(rev)

            context.attach(rev)

        if ext.cell is None:
            ext.add_to_deferred(rev)
        else:
            with MeasureExecution("Annotators"):
                # Annotate the revision
                self.annotate(rev)

        with MeasureExecution("Image data"):
            rev.image_data, image_to_display = self._get_image_data(gf, backend, fig, rev, image_options)

        if image_to_display is not None and self.show_watermark:
            with SuppressDisplayTrap():
                if isinstance(image_to_display, gf.ImageData):
                    display(image_to_display.image)
                else:
                    display(image_to_display)

            if suppress_display is not None:
                suppress_display()

        if dataframes is not None:
            table_data = []
            for name, frame in dataframes.items():
                table_data.append(gf.TableData(name=name, dataframe=frame))

            rev.table_data = table_data

        if files is not None:
            rev.file_data = self._prepare_files(gf, files)

        with MeasureExecution("Final save"):
            rev.save(silent=True)

            # Calling .save() above will update internal properties based on the response from the server.
            # In our case, this will result in rev.figure becoming a shallow object with just the API ID. Here
            # we restore it from our cached copy, to avoid a separate API call.
            rev.figure = target

        _mark_as_published(fig)

        if self.clear and self.show_watermark:
            backend.close(fig)

        with SuppressDisplayTrap():
            self.widget_class(rev).show()

        return rev


ApiId = namedtuple("ApiId", ["api_id"])

class FindByName:
    """\
    Used as argument to configure() to specify that we want to find an analysis/workspace by name instead
    of using an API ID
    """
    def __init__(self, name, description=None, create=False):
        self.name = name
        self.description = description
        self.create = create

    def __repr__(self):
        return f"FindByName(name={self.name}, description={self.description}, create={self.create})"


def parse_model_instance(model_class, value, find_by_name):
    """\
    Parses a model instance from a value, e.g. the API ID or a name.

    :param model_class: class of the model, e.g. gf.Workspace
    :param value: value to parse into a model instance
    :param find_by_name: callable to find the model instance by name
    :return: model instance

    """
    if isinstance(value, model_class):
        return value
    elif isinstance(value, str):
        return model_class(api_id=value)
    elif isinstance(value, ApiId):
        return model_class(api_id=value.api_id)
    elif isinstance(value, FindByName):
        return find_by_name(value)
    else:
        return ValueError(f"Unsupported target specification: {value}. Please specify an API ID, or use FindByName.")


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

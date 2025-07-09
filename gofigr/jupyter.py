"""\
Copyright (c) 2022, Flagstaff Solutions, LLC
All rights reserved.

"""
# pylint: disable=cyclic-import, no-member, global-statement, protected-access
# pylint: disable=too-many-locals

import io
import os
import pickle
import sys
import traceback
from functools import wraps
from pathlib import Path
from uuid import UUID

import gofigr
from gofigr import GoFigr, API_URL
from gofigr.annotators import NotebookMetadataAnnotator, NOTEBOOK_NAME, NOTEBOOK_PATH, IPythonAnnotator
from gofigr.publisher import Publisher, DEFAULT_ANNOTATORS, DEFAULT_BACKENDS, _mark_as_published, is_published, \
    is_suppressed
from gofigr.proxy import run_proxy_async, get_javascript_loader
from gofigr.profile import MeasureExecution
from gofigr.trap import GfDisplayPublisher, SuppressDisplayTrap
from gofigr.utils import from_config_or_env
from gofigr.widget import DetailedWidget, StartupWidget

try:
    from IPython.core.display_functions import display
except ModuleNotFoundError:
    from IPython.core.display import display


# pylint: disable=too-many-instance-attributes
class _GoFigrExtension:
    """\
    Implements the main Jupyter extension functionality. You will not want to instantiate this class directly.
    Instead, please call get_extension().
    """
    def __init__(self, ip,
                 auto_publish=False,
                 notebook_metadata=None,
                 configured=False,
                 loader_shown=False,
                 asset_log=None):
        """\

        :param ip: iPython shell instance
        :param auto_publish: whether to auto-publish figures
        :param pre_run_hook: function to use as a pre-run hook
        :param post_execute_hook: function to use as a post-execute hook
        :param notebook_metadata: information about the running notebook, as a key-value dictionary

        """
        self.shell = ip
        self.auto_publish = auto_publish
        self.cell = None
        self.proxy = None
        self.loader_shown = loader_shown
        self.configured = configured
        if notebook_metadata is None:
            self.notebook_metadata = NotebookMetadataAnnotator().try_get_metadata()
        else:
            self.notebook_metadata = notebook_metadata

        self.gf = None  # active GF object
        self.publisher = None  # current Publisher instance
        self.wait_for_metadata = None  # callable which waits for metadata to become available
        self.asset_log = asset_log if asset_log is not None else {}

        self.deferred_revisions = []

    @property
    def is_ready(self):
        """True if the extension has been configured and ready for use."""
        return self.configured and self.notebook_metadata is not None

    def resolve_analysis(self):
        """Gets the current analysis"""
        if isinstance(self.publisher.analysis, gofigr.NotebookName):
            meta = NotebookMetadataAnnotator().try_get_metadata()
            if meta is not None:
                self.publisher.analysis = self.publisher.workspace.get_analysis(name=Path(meta[NOTEBOOK_NAME]).stem,
                                                                                create=True)
                self.publisher.analysis.fetch()

        return self.publisher.analysis

    def display_trap(self, data, suppress_display):
        """\
         Called whenever *any* code inside the Jupyter session calls display().
        :param data: dictionary of MIME types
        :param suppress_display: callable with no arguments. Call to prevent the originating figure from being shown.
        :return: None

        """
        if self.auto_publish:
            self.publisher.auto_publish_hook(self, data, suppress_display)

    def add_to_deferred(self, rev):
        """\
        Adds a revision to a list of deferred revisions. Such revisions will be annotated in the post_run_cell
        hook, and re-saved.

        This functionality exists because it's possible to load the GoFigr extension and publish figures in the same
        cell, in which case GoFigr will not receive the pre_run_cell hook and will not have access to cell information
        when the figure is published. This functionality allows us to obtain the cell information after it's run
        (in the post_run_cell hook), re-run annotators, and update the figure with full annotations.

        :param rev: revision to defer
        :return: None
        """
        if rev not in self.deferred_revisions:
            self.deferred_revisions.append(rev)

    def check_config(self):
        """Ensures the plugin has been configured for use"""
        if not self.configured:
            raise RuntimeError("GoFigr not configured. Please call configure() first.")

    def pre_run_cell(self, info):
        """\
        Default pre-run cell hook.

        :param info: Cell object
        :return:None

        """
        self.cell = info

    def _get_metadata_from_proxy(self, result):
        if self.configured and not self.loader_shown and "_VSCODE" not in result.info.raw_cell:
            self.proxy, self.wait_for_metadata = run_proxy_async(self.gf, proxy_callback)

            with SuppressDisplayTrap():
                display(get_javascript_loader(self.gf, self.proxy))
                self.loader_shown = True

        if self.notebook_metadata is None and self.wait_for_metadata is not None:
            self.wait_for_metadata()
            self.wait_for_metadata = None


    def post_run_cell(self, result):
        """Post run cell hook.

        :param result: ExecutionResult
        :return: None

        """
        self.cell = result.info

        if self.notebook_metadata is None:
            self._get_metadata_from_proxy(result)

        while len(self.deferred_revisions) > 0:
            rev = self.deferred_revisions.pop(0)
            rev = self.publisher.annotate(rev)
            rev.save(silent=True)

        self.cell = None

    def _register_handler(self, event_name, handler):
        """Inserts a handler at the beginning of the list while avoiding double-insertions"""
        handlers = [handler]
        for hnd in self.shell.events.callbacks[event_name]:
            self.shell.events.unregister(event_name, hnd)
            if hnd != handler:  # in case it's already registered, skip it
                handlers.append(hnd)

        for hnd in handlers:
            self.shell.events.register(event_name, hnd)

    def unregister(self):
        """\
        Unregisters all hooks, effectively disabling the plugin.

        """
        try:
            self.shell.events.unregister('pre_run_cell', self.pre_run_cell)
        except ValueError:
            pass

        try:
            self.shell.events.unregister('post_run_cell', self.post_run_cell)
        except ValueError:
            pass

    def register_hooks(self):
        """\
        Register all hooks with Jupyter.

        :return: None
        """
        self._register_handler('pre_run_cell', self.pre_run_cell)
        self._register_handler('post_run_cell', self.post_run_cell)

        native_display_publisher = self.shell.display_pub
        if not isinstance(native_display_publisher, GfDisplayPublisher):
            self.shell.display_pub = GfDisplayPublisher(native_display_publisher, display_trap=self.display_trap)


_GF_EXTENSION = None  # GoFigrExtension global


def require_configured(func):
    """\
    Decorator which throws an exception if configure() has not been called yet.

    :param func:
    :return:
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        if _GF_EXTENSION is None:
            raise RuntimeError("Please load the extension: %load_ext gofigr")
        _GF_EXTENSION.check_config()

        return func(*args, **kwargs)

    return wrapper


@require_configured
def get_extension():
    """Returns the GoFigr Jupyter extension instance"""
    return _GF_EXTENSION


def _load_ipython_extension(ip):
    """\
    Loads the Jupyter extension. Aliased to "load_ipython_extension" (no leading underscore) in the main init.py file.

    :param ip: IPython shell
    :return: None

    """
    global _GF_EXTENSION
    if _GF_EXTENSION is not None:
        _GF_EXTENSION.unregister()

    _GF_EXTENSION = _GoFigrExtension(ip)
    _GF_EXTENSION.register_hooks()

    try:
        configure()
    except Exception as e:  # pylint: disable=broad-exception-caught
        if "auth" in str(e).lower() and "failed" in str(e).lower():
            print("GoFigr authentication failed. Please manually call configure(api_key=<YOUR API KEY>).",
                  file=sys.stderr)
        else:
            print(traceback.format_exc(), file=sys.stderr)
            print(f"Could not automatically configure GoFigr. Please call configure() manually. Error: {e}",
                  file=sys.stderr)

    ip.user_ns["configure"] = configure
    ip.user_ns["get_extension"] = get_extension
    ip.user_ns["publish"] = publish

    # These have to use the fully qualified reference or isinstance won't work correctly
    # after the extension is re-loaded. That's because gofigr.FindByName and gofigr.jupyter.FindByName (imported scope)
    # will contain different instantiations of the type.
    ip.user_ns["FindByName"] = gofigr.FindByName
    ip.user_ns["ApiId"] = gofigr.ApiId
    ip.user_ns["NotebookName"] = gofigr.NotebookName


def parse_uuid(val):
    """\
    Attempts to parse a UUID, returning None if input is not a valid UUID.

    :param val: value to parse
    :return: UUID (as a string) or None

    """
    try:
        return str(UUID(val))
    except ValueError:
        return None


def proxy_callback(result):
    """Proxy callback"""
    if result is not None and hasattr(result, 'metadata'):
        get_extension().notebook_metadata = result.metadata
        get_extension().resolve_analysis()

        if get_extension().is_ready:
            StartupWidget(get_extension()).show()


class JupyterPublisher(Publisher):
    """\
    Adds Jupyter-specific functionality to GoFigr's base Publisher class.

    """
    def __init__(self, *args, clear=True, **kwargs):
        super().__init__(*args, clear=clear, **kwargs)

    @property
    def _non_ipython_annotators(self):
        return [ann for ann in self.annotators if not isinstance(ann, IPythonAnnotator)]

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
                if not is_published(fig) and not is_suppressed(fig):
                    self.publish(fig=fig, backend=backend, suppress_display=suppress_display)

            if len(compatible_figures) > 0:
                break

    def publish(self, *args, **kwargs):
        with SuppressDisplayTrap():
            ext = get_extension()

            if ext.cell is None:
                revision = super().publish(*args, annotators=self._non_ipython_annotators, **kwargs)
                ext.add_to_deferred(revision)
            else:
                revision = super().publish(*args, **kwargs)
            return revision


# pylint: disable=too-many-arguments, too-many-locals
@from_config_or_env("GF_", gofigr.find_config())
def configure(username=None,
              password=None,
              api_key=None,
              workspace=None,
              analysis=gofigr.NotebookName(),
              url=API_URL,
              default_metadata=None, auto_publish=True,
              watermark=None, annotators=DEFAULT_ANNOTATORS,
              notebook_name=None, notebook_path=None,
              backends=DEFAULT_BACKENDS,
              widget_class=DetailedWidget,
              save_pickle=True,
              show_watermark=True):
    """\
    Configures the Jupyter plugin for use.

    :param username: GoFigr username (if used instead of API key)
    :param password: GoFigr password (if used instead of API key)
    :param api_key: API Key (if used instead of username and password)
    :param url: API URL
    :param workspace: one of: API ID (string), ApiId instance, or FindByName instance
    :param analysis: one of: API ID (string), ApiId instance, FindByName, or NotebookName instance
    :param default_metadata: dictionary of default metadata values to save for each revision
    :param auto_publish: if True, all figures will be published automatically without needing to call publish()
    :param watermark: custom watermark instance (e.g. DefaultWatermark with custom arguments)
    :param annotators: list of annotators to use. Default: DEFAULT_ANNOTATORS
    :param notebook_name: name of the notebook (if you don't want it to be inferred automatically)
    :param notebook_path: path to the notebook (if you don't want it to be inferred automatically)
    :param backends: backends to use (e.g. MatplotlibBackend, PlotlyBackend)
    :param widget_class: Widget type to show, e.g. DetailedWidget or CompactWidget. It will appear below the
        published figure
    :param save_pickle: if True, will save the figure in pickle format in addition to any of the image formats
    :param show_watermark: True to show watermarked figures instead of original.
        False to always display the unmodified figure. Default True.
    :return: None

    """
    extension = _GF_EXTENSION

    if isinstance(auto_publish, str):
        auto_publish = auto_publish.lower() == "true"  # in case it's coming from an environment variable

    with MeasureExecution("Login"):
        gf = GoFigr(username=username, password=password, url=url, api_key=api_key,
                    asset_log=extension.asset_log)

    if default_metadata is None:
        default_metadata = {}

    if notebook_path is not None:
        default_metadata[NOTEBOOK_PATH] = notebook_path

    if notebook_name is not None:
        default_metadata[NOTEBOOK_NAME] = notebook_name

    if str(analysis) == "NotebookName":  # str in case it's from config/env
        analysis = gofigr.NotebookName()

    worx = gf.find_workspace(workspace)
    publisher = JupyterPublisher(gf,
                                 workspace=worx,
                                 analysis=gf.find_analysis(worx, analysis),
                                 default_metadata=default_metadata,
                                 watermark=watermark,
                                 annotators=[make_annotator() for make_annotator in annotators],
                                 backends=backends,
                                 widget_class=widget_class,
                                 save_pickle=save_pickle,
                                 show_watermark=show_watermark)
    extension.gf = gf
    extension.publisher = publisher
    extension.auto_publish = auto_publish
    extension.loader_shown = False
    extension.configured = True
    extension.resolve_analysis()

    extension.shell.user_ns["gf"] = gf

    if get_extension().is_ready:
        StartupWidget(get_extension()).show()


@require_configured
def publish(fig=None, backend=None, **kwargs):
    """\
    Publishes a figure. See :func:`gofigr.jupyter.Publisher.publish` for a list of arguments. If figure and backend
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


@require_configured
def get_gofigr():
    """Gets the active GoFigr object."""
    return get_extension().gf


@require_configured
def load_pickled_figure(api_id):
    """\
    Unpickles a GoFigr revision and returns it as a backend-specific Python object, e.g. a plt.Figure if
    the figure was generated with matplotlib. Throws a RuntimeException if the figure is not found or does
    not have pickle data.

    :param api_id: API ID of the revision
    :return: backend-dependent figure object, e.g. plt.Figure().

    """
    gf = get_gofigr()
    rev = gf.Revision(api_id=api_id).fetch(fetch_data=False)
    for data in rev.image_data:
        if data.format == "pickle":
            data.fetch()

            fig = pickle.load(io.BytesIO(data.data))
            return _mark_as_published(fig)

    raise RuntimeError("This revision doesn't have pickle data.")


@require_configured
def download_file(api_id, file_name, path):
    """\
    Downloads a file and saves it.

    :param api_id: API ID of the revision containing the file
    :param file_name: name of the file to download
    :param path: where to save the file (either existing directory or full path with the file name)
    :return: number of bytes written

    """
    if os.path.exists(path) and os.path.isdir(path):
        path = os.path.join(path, file_name)

    gf = get_gofigr()
    rev = gf.Revision(api_id=api_id).fetch(fetch_data=False)
    for data in rev.file_data:
        if data.name == file_name:
            data.fetch()
            data.write(path)
            return len(data.data)

    raise RuntimeError(f"Could not find file \"{file_name}\" in revision {api_id}.")


@require_configured
def download_all(api_id, path):
    """\
    Downloads all files attached to a revision

    :param api_id: API ID of the revision containing the files
    :param path: directory where to save the files
    :return: number of bytes written

    """
    if not os.path.exists(path) or not os.path.isdir(path):
        raise RuntimeError(f"{path} does not exist or is not a directory")

    gf = get_gofigr()
    rev = gf.Revision(api_id=api_id).fetch(fetch_data=False)
    num_bytes = 0
    for data in rev.file_data:
        data.fetch()
        data.write(os.path.join(path, data.name))
        num_bytes += len(data.data)

    return num_bytes

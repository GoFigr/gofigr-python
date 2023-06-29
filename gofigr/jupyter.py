"""\
Copyright (c) 2022, Flagstaff Solutions, LLC
All rights reserved.

"""

# pylint: disable=cyclic-import, no-member, global-statement, protected-access, wrong-import-order

import inspect
import io
import json
import os
import sys
from collections import namedtuple
from functools import wraps
from uuid import UUID

import PIL
import six

from gofigr import GoFigr, API_URL
from gofigr.annotators import NotebookNameAnnotator, CellIdAnnotator, SystemAnnotator, CellCodeAnnotator, \
    PipFreezeAnnotator
from gofigr.backends import get_backend
from gofigr.backends.matplotlib import MatplotlibBackend
from gofigr.backends.plotly import PlotlyBackend
from gofigr.listener import run_listener_async
from gofigr.watermarks import DefaultWatermark

try:
    from IPython.core.display_functions import display
except ModuleNotFoundError:
    from IPython.core.display import display

from IPython.core.display import Javascript


class _GoFigrExtension:
    """\
    Implements the main Jupyter extension functionality. You will not want to instantiate this class directly.
    Instead, please refer to the _GF_EXTENSION singleton.
    """
    def __init__(self, ip, pre_run_hook=None, post_execute_hook=None, notebook_metadata=None):
        """\

        :param ip: iPython shell instance
        :param pre_run_hook: function to use as a pre-run hook
        :param post_execute_hook: function to use as a post-execute hook
        :param notebook_metadata: information about the running notebook, as a key-value dictionary

        """
        self.shell = ip
        self.cell = None
        self.notebook_metadata = notebook_metadata

        self.pre_run_hook = pre_run_hook
        self.post_execute_hook = post_execute_hook

        self.gf = None  # active GF object
        self.workspace = None  # current workspace
        self.analysis = None  # current analysis
        self.publisher = None  # current Publisher instance

    def check_config(self):
        """Ensures the plugin has been configured for use"""
        props = ["gf", "workspace", "analysis", "publisher"]
        for prop in props:
            if getattr(self, prop, None) is None:
                raise RuntimeError("GoFigr not configured. Please call configure() first.")

    def pre_run_cell(self, info):
        """\
        Default pre-run cell hook. Delegates to self.pre_run_hook if set.

        :param info: Cell object
        :return:

        """
        self.cell = info

        if self.pre_run_hook is not None:
            self.pre_run_hook(self, info)

    def post_execute(self):
        """\
        Post-execute hook. Delegates to self.post_execute_hook() if set.
        """
        if self.post_execute_hook is not None:
            self.post_execute_hook(self)

    def register_hooks(self):
        """\
        Register all hooks with Jupyter.

        :return: None
        """
        self.shell.events.register('pre_run_cell', self.pre_run_cell)

        # Unregister all handlers first, then re-register with our hook first in the queue.
        # This is kind of gross, but the official interface doesn't have an explicit way to specify order.
        handlers = []
        for handler in self.shell.events.callbacks['post_execute']:
            self.shell.events.unregister('post_execute', handler)
            handlers.append(handler)

        handlers = [self.post_execute] + handlers
        for handler in handlers:
            self.shell.events.register('post_execute', handler)


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
        return

    _GF_EXTENSION = _GoFigrExtension(ip)
    _GF_EXTENSION.register_hooks()


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


DEFAULT_ANNOTATORS = (NotebookNameAnnotator, CellIdAnnotator, CellCodeAnnotator, SystemAnnotator,
                      PipFreezeAnnotator)
DEFAULT_BACKENDS = (MatplotlibBackend, PlotlyBackend)


class Publisher:
    """\
    Publishes revisions to the GoFigr server.
    """
    def __init__(self,
                 gf,
                 annotators,
                 backends=DEFAULT_BACKENDS,
                 watermark=None,
                 image_formats=("png", "eps", "svg"),
                 default_metadata=None,
                 clear=True):
        """

        :param gf: GoFigr instance
        :param annotators: revision annotators
        :param backends: figure backends, e.g. MatplotlibBackend
        :param watermark: watermark generator, e.g. QRWatermark()
        :param image_formats: image formats to save by default
        :param clear: whether to close the original figures after publication. If False, Jupyter will display
        both the input figure and the watermarked output. Default behavior is to close figures.

        """
        self.gf = gf
        self.watermark = watermark or DefaultWatermark()
        self.annotators = annotators
        self.backends = [back() for back in backends]
        self.image_formats = image_formats
        self.clear = clear
        self.default_metadata = default_metadata

    def auto_publish_hook(self, extension):
        """\
        Hook for automatically publishing figures without an explicit call to publish().

        :return: None
        """
        for backend in self.backends:
            for fig in backend.find_figures(extension.shell):
                if not getattr(fig, '_gf_is_published', False):
                    self.publish(fig=fig, backend=backend)

    @staticmethod
    def _resolve_target(gf, fig, target, backend):
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
            return _GF_EXTENSION.analysis.get_figure(fig_name, create=True)
        else:
            return parse_model_instance(gf.Figure,
                                        target,
                                        lambda search: _GF_EXTENSION.analysis.get_figure(name=search.name,
                                                                                         description=search.description,
                                                                                         create=search.create))

    def publish(self, fig=None, target=None, gf=None, dataframes=None, metadata=None, return_revision=False,
                backend=None):
        """\
        Publishes a revision to the server.

        :param fig: figure to publish. If None, we'll use plt.gcf()
        :param target: Target figure to publish this revision under. Can be a gf.Figure instance, an API ID, \
        or a FindByName instance.
        :param gf: GoFigure instance
        :param dataframes: dictionary of dataframes to associate & publish with the figure
        :param metadata: metadata (JSON) to attach to this revision
        :param return_revision: whether to return a FigureRevision object. This is optional, because in normal Jupyter \
        usage this will cause Jupyter to print the whole object which we don't want.
        :param backend: backend to use, e.g. MatplotlibBackend. If None it will be inferred automatically based on \
        figure type
        :return: FigureRevision instance

        """
        # pylint: disable=too-many-locals, too-many-branches

        if _GF_EXTENSION.cell is None:
            print("Information about current cell is unavailable and certain features like source code capture will " +
                  "not work. Did you call configure() and try to publish a " +
                  "figure in the same cell? If so, we recommend keeping GoFigr configuration and figures in " +
                  "separate cells",
                  file=sys.stderr)

        if gf is None:
            gf = _GF_EXTENSION.gf

        if fig is None:
            if backend is not None:
                fig = backend.get_default_figure()

                if fig is None:
                    raise ValueError("You did not specify a figure to publish.")
            else:
                raise ValueError("You did not specify a figure to publish.")
        elif fig is not None and backend is None:
            backend = get_backend(fig, self.backends)

        target = self._resolve_target(gf, fig, target, backend)

        combined_meta = self.default_metadata if self.default_metadata is not None else {}
        if metadata is not None:
            combined_meta.update(metadata)

        # Create a bare revision first to get the API ID
        rev = gf.Revision(figure=target, metadata=combined_meta)
        target.revisions.create(rev)

        image_data = []
        for fmt in self.image_formats:
            if fmt.lower() == "png":
                img = PIL.Image.open(io.BytesIO(backend.figure_to_bytes(fig, fmt)))
                img.load()
                watermarked_img = self.watermark.apply(img, rev)
            else:
                watermarked_img = None

            # First, save the image without the watermark
            try:
                image_data.append(gf.ImageData(name="figure", format=fmt, data=backend.figure_to_bytes(fig, fmt),
                                               is_watermarked=False))
            except Exception as e:
                print(f"WARNING: We could not obtain the figure in {fmt.upper()} format: {e}", file=sys.stderr)
                continue

            # Now, save the watermarked version (if available)
            if watermarked_img is not None:
                bio = io.BytesIO()
                watermarked_img.save(bio, format=fmt)
                image_data.append(gf.ImageData(name="figure", format=fmt, data=bio.getvalue(),
                                               is_watermarked=True))

            if fmt.lower() == 'png' and watermarked_img is not None:
                display(watermarked_img)

        rev.image_data = image_data

        if dataframes is not None:
            table_data = []
            for name, frame in dataframes.items():
                table_data.append(gf.TableData(name=name, dataframe=frame))

            rev.table_data = table_data

        # Annotate the revision
        for annotator in self.annotators:
            annotator.annotate(rev)

        rev.save(silent=True)

        fig._gf_is_published = True

        if self.clear:
            backend.close(fig)

        print(f"{gf.app_url}/r/{rev.api_id}")

        return rev if return_revision else None


def from_config_or_env(env_prefix, config_path):
    """\
    Decorator that binds function arguments in order of priority (most important first):
    1. args/kwargs
    2. environment variables
    3. config file
    4. function defaults

    :param env_prefix: prefix for environment variables. Variables are assumed to be named \
    `<prefix> + <name of function argument in all caps>`, e.g. if prefix is ``MYAPP`` and function argument \
    is called host_name, we'll look for an \
    environment variable named ``MYAPP_HOST_NAME``.
    :param config_path: path to the JSON config file. Function arguments will be looked up using their verbatim names.
    :return: decorated function

    """
    def decorator(func):
        @six.wraps(func)
        def wrapper(*args, **kwargs):
            # Read config file, if it exists
            if os.path.exists(config_path):
                with open(config_path, 'r', encoding='utf-8') as f:
                    try:
                        config_file = json.load(f)
                    except Exception as e:
                        raise RuntimeError(f"Error parsing configuration file {config_path}") from e
            else:
                config_file = {}

            sig = inspect.signature(func)
            param_values = sig.bind_partial(*args, **kwargs).arguments
            for param_name in sig.parameters:
                env_name = f'{env_prefix}{param_name.upper()}'
                if param_name in param_values:
                    continue  # value supplied through args/kwargs: ignore env variables and the config file.
                elif env_name in os.environ:
                    param_values[param_name] = os.environ[env_name]
                elif param_name in config_file:
                    param_values[param_name] = config_file[param_name]

            return func(**param_values)

        return wrapper

    return decorator


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


def listener_callback(result):
    """WebSocket callback"""
    if result is not None and isinstance(result, dict) and result['message_type'] == "metadata":
        _GF_EXTENSION.notebook_metadata = result


# pylint: disable=too-many-arguments
@from_config_or_env("GF_", os.path.join(os.environ['HOME'], '.gofigr'))
def configure(username, password, workspace=None, analysis=None, url=API_URL,
              default_metadata=None, auto_publish=True,
              watermark=None, annotators=DEFAULT_ANNOTATORS,
              notebook_name=None, notebook_path=None):
    """\
    Configures the Jupyter plugin for use.

    :param username: GoFigr username
    :param password: GoFigr password
    :param url: API URL
    :param workspace: one of: API ID (string), ApiId instance, or FindByName instance
    :param analysis: one of: API ID (string), ApiId instance, or FindByName instance
    :param default_metadata: dictionary of default metadata values to save for each revision
    :param auto_publish: if True, all figures will be published automatically without needing to call publish()
    :param watermark: custom watermark instance (e.g. DefaultWatermark with custom arguments)
    :param annotators: list of annotators to use. Default: DEFAULT_ANNOTATORS
    :param notebook_name: name of the notebook (if you don't want it to be inferred automatically)
    :param notebook_path: path to the notebook (if you don't want it to be inferred automatically)
    :return: None

    """
    extension = _GF_EXTENSION

    if isinstance(auto_publish, str):
        auto_publish = auto_publish.lower() == "true"  # in case it's coming from an environment variable

    gf = GoFigr(username=username, password=password, url=url)

    if workspace is None:
        workspace = gf.primary_workspace
    else:
        workspace = parse_model_instance(gf.Workspace, workspace, lambda search: find_workspace_by_name(gf, search))

    workspace.fetch()

    if analysis is None:
        raise ValueError("Please specify an analysis")
    else:
        analysis = parse_model_instance(gf.Analysis, analysis,
                                        lambda search: workspace.get_analysis(name=search.name,
                                                                              description=search.description,
                                                                              create=search.create))

    analysis.fetch()

    if default_metadata is None:
        default_metadata = {}

    if notebook_path is not None:
        default_metadata['notebook_path'] = notebook_path

    if notebook_name is not None:
        default_metadata['notebook_name'] = notebook_name

    publisher = Publisher(gf, default_metadata=default_metadata,
                          watermark=watermark, annotators=[make_annotator(extension) for make_annotator in annotators])
    extension.gf = gf
    extension.analysis = analysis
    extension.workspace = workspace
    extension.publisher = publisher

    if auto_publish:
        extension.post_execute_hook = publisher.auto_publish_hook

    listener_port = run_listener_async(listener_callback)

    display(Javascript(f"""
    var ws_url = "ws://" + window.location.hostname + ":{listener_port}";

    document._ws_gf = new WebSocket(ws_url);
    document._ws_gf.onopen = () => {{
      console.log("GoFigr WebSocket open at " + ws_url);
      document._ws_gf.send(JSON.stringify(
      {{
        message_type: "metadata",
        url: document.URL
      }}))
    }}
    """))


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
    if fig is None and backend is None:
        # If no figure and no backend supplied, publish default figures across all available backends
        for available_backend in _GF_EXTENSION.publisher.backends:
            fig = available_backend.get_default_figure(silent=True)
            if fig is not None:
                _GF_EXTENSION.publisher.publish(fig=fig, backend=available_backend, **kwargs)
    else:
        _GF_EXTENSION.publisher.publish(fig=fig, backend=backend, **kwargs)


@require_configured
def get_gofigr():
    """Gets the active GoFigr object."""
    return _GF_EXTENSION.gf

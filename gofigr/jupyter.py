"""\
Copyright (c) 2022, Flagstaff Solutions, LLC
All rights reserved.

"""

# pylint: disable=cyclic-import, no-member, global-statement, protected-access

import inspect
import io
import json
import os
import subprocess
import sys
from collections import namedtuple
from functools import wraps
from uuid import UUID

import PIL
import ipynbname
import matplotlib.pyplot as plt
import six

try:
    from IPython.core.display_functions import display
except ModuleNotFoundError:
    from IPython.core.display import display

from gofigr import GoFigr, CodeLanguage, API_URL
from gofigr.watermarks import DefaultWatermark


class _GoFigrExtension:
    """\
    Implements the main Jupyter extension functionality. You will not want to instantiate this class directly.
    Instead, please refer to the _GF_EXTENSION singleton.
    """
    def __init__(self, ip, pre_run_hook=None, post_execute_hook=None):
        """\

        :param ip: iPython shell instance
        :param pre_run_hook: function to use as a pre-run hook
        :param post_execute_hook: function to use as a post-execute hook

        """
        self.shell = ip
        self.cell = None

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
            self.pre_run_hook(info)

    def post_execute(self):
        """\
        Post-execute hook. Delegates to self.post_execute_hook() if set.
        """
        if self.post_execute_hook is not None:
            self.post_execute_hook()

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


class Annotator:
    """\
    Annotates figure revisions with pertinent information, such as cell code, variable values, etc.

    """
    def annotate(self, revision):
        """
        Annotates the figure revision.

        :param revision: FigureRevision
        :return: annotated FigureRevision

        """
        return revision


class NotebookNameAnnotator(Annotator):
    """"Annotates revisions with the name & path of the current notebook"""
    def annotate(self, revision):
        if revision.metadata is None:
            revision.metadata = {}

        try:
            if 'notebook_name' not in revision.metadata:
                revision.metadata['notebook_name'] = ipynbname.name()
            if 'notebook_path' not in revision.metadata:
                revision.metadata['notebook_path'] = str(ipynbname.path())

        except Exception:  # pylint: disable=broad-exception-caught
            print("GoFigr could not automatically obtain the name of the currently running notebook. To fix this error,"
                  " you can manually specify the notebook name & path in the call to configure(). "
                  "Please see https://gofigr.io/docs/gofigr-python/latest/customization.html#notebook-name-path "
                  "for details.",
                  file=sys.stderr)

            revision.metadata['notebook_name'] = "N/A"
            revision.metadata['notebook_path'] = "N/A"

        return revision


class CellIdAnnotator(Annotator):
    """Annotates revisions with the ID of the Jupyter cell"""
    def annotate(self, revision):
        if revision.metadata is None:
            revision.metadata = {}

        try:
            cell_id = _GF_EXTENSION.cell.cell_id
        except AttributeError:
            cell_id = None

        revision.metadata['cell_id'] = cell_id

        return revision


class CellCodeAnnotator(Annotator):
    """"Annotates revisions with cell contents"""
    def annotate(self, revision):
        if _GF_EXTENSION.cell is not None:
            code = _GF_EXTENSION.cell.raw_cell
        else:
            code = "N/A"

        revision.data.append(_GF_EXTENSION.gf.CodeData(name="Jupyter Cell",
                                                       language=CodeLanguage.PYTHON,
                                                       contents=code))
        return revision


class PipFreezeAnnotator(Annotator):
    """Annotates revisions with the output of pip freeze"""
    def annotate(self, revision):
        try:
            output = subprocess.check_output(["pip", "freeze"]).decode('ascii')
        except subprocess.CalledProcessError as e:
            output = e.output

        revision.data.append(_GF_EXTENSION.gf.TextData(name="pip freeze", contents=output))
        return revision


class SystemAnnotator(Annotator):
    """Annotates revisions with the OS version"""
    def annotate(self, revision):
        try:
            output = subprocess.check_output(["uname", "-a"]).decode('ascii')
        except subprocess.CalledProcessError as e:
            output = e.output

        revision.data.append(_GF_EXTENSION.gf.TextData(name="System Info", contents=output))
        return revision


DEFAULT_ANNOTATORS = (NotebookNameAnnotator(), CellIdAnnotator(), CellCodeAnnotator(), SystemAnnotator(),
                      PipFreezeAnnotator())


def figure_to_bytes(fig, fmt):
    """\
    Converts a matplotlib figure to raw bytes

    :param fig: matplotlib figure
    :param fmt: format as a string, e.g. "png", "eps", etc.
    :return: bytes

    """
    bio = io.BytesIO()
    fig.savefig(bio, format=fmt)

    bio.seek(0)
    return bio.read()


class Publisher:
    """\
    Publishes revisions to the GoFigr server.
    """
    def __init__(self, gf, watermark=None, annotators=DEFAULT_ANNOTATORS, image_formats=("png", "eps", "svg"),
                 default_metadata=None, clear=True):
        """

        :param gf: GoFigr instance
        :param watermark: watermark generator, e.g. QRWatermark()
        :param annotators: revision annotators
        :param image_formats: image formats to save by default
        :param clear: whether to close the original figures after publication. If False, Jupyter will display
        both the input figure and the watermarked output. Default behavior is to close figures.

        """
        self.gf = gf
        self.watermark = watermark or DefaultWatermark()
        self.annotators = annotators
        self.image_formats = image_formats
        self.clear = clear
        self.default_metadata = default_metadata

    def auto_publish_hook(self):
        """\
        Hook for automatically publishing figures without an explicit call to publish().

        :return: None
        """
        for num in plt.get_fignums():
            fig = plt.figure(num)
            if not getattr(fig, '_gf_is_published', False):
                self.publish(fig=fig)

    @staticmethod
    def _resolve_target(gf, fig, target):
        if target is None:
            # Try to get the figure's title
            suptitle = getattr(fig, "_suptitle", "")
            title = fig.axes[0].get_title() if len(fig.axes) > 0 else None
            if suptitle is not None and suptitle.strip() != "":
                fig_name = suptitle
            elif title is not None and title.strip() != "":
                fig_name = title
            else:
                print("Your figure doesn't have a title and will be published as 'Anonymous Figure'. "
                      "To avoid this warning, set a figure title or manually call publish() with a target figure. "
                      "See https://gofigr.io/docs/gofigr-python/latest/start.html#publishing-your-first-figure for "
                      "an example.", file=sys.stderr)
                fig_name = "Anonymous Figure"

            return _GF_EXTENSION.analysis.get_figure(fig_name, create=True)
        else:
            return parse_model_instance(gf.Figure,
                                        target,
                                        lambda search: _GF_EXTENSION.analysis.get_figure(name=search.name,
                                                                                         description=search.description,
                                                                                         create=search.create))

    def publish(self, fig=None, target=None, gf=None, dataframes=None, metadata=None, return_revision=False):
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
            fig = plt.gcf()

        target = self._resolve_target(gf, fig, target)

        combined_meta = self.default_metadata if self.default_metadata is not None else {}
        if metadata is not None:
            combined_meta.update(metadata)

        # Create a bare revision first to get the API ID
        rev = gf.Revision(figure=target, metadata=combined_meta)
        target.revisions.create(rev)

        image_data = []
        for fmt in self.image_formats:
            if fmt.lower() == "png":
                img = PIL.Image.open(io.BytesIO(figure_to_bytes(fig, fmt)))
                img.load()
                watermarked_img = self.watermark.apply(img, rev)
            else:
                watermarked_img = None

            # First, save the image without the watermark
            image_data.append(gf.ImageData(name="figure", format=fmt, data=figure_to_bytes(fig, fmt),
                                           is_watermarked=False))

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
            plt.close(fig)

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
                          watermark=watermark, annotators=annotators)
    extension.gf = gf
    extension.analysis = analysis
    extension.workspace = workspace
    extension.publisher = publisher

    if auto_publish:
        extension.post_execute_hook = publisher.auto_publish_hook


@require_configured
def publish(*args, **kwargs):
    """\
    Publishes a figure. See :func:`gofigr.jupyter.Publisher.publish` for a list of arguments.

    :param args:
    :param kwargs:
    :return:
    """
    return _GF_EXTENSION.publisher.publish(*args, **kwargs)


@require_configured
def get_gofigr():
    """Gets the active GoFigr object."""
    return _GF_EXTENSION.gf

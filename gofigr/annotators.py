"""\
Copyright (c) 2023, Flagstaff Solutions, LLC
All rights reserved.

"""
import os
import subprocess
import sys
from abc import ABC
from urllib.parse import unquote, urlparse

from gofigr import CodeLanguage

PATH_WARNING = "To fix this warning, you can manually specify the notebook name & path in the call to configure(). " \
               "Please see https://gofigr.io/docs/gofigr-python/latest/customization.html#notebook-name-path " \
               "for details."


class Annotator(ABC):
    """\
    Annotates figure revisions with pertinent information, such as cell code, variable values, etc.

    """
    def __init__(self, extension):
        self.extension = extension

    def annotate(self, revision):
        """
        Annotates the figure revision.

        :param revision: FigureRevision
        :return: annotated FigureRevision

        """
        return revision


class CellIdAnnotator(Annotator):
    """Annotates revisions with the ID of the Jupyter cell"""
    def annotate(self, revision):
        if revision.metadata is None:
            revision.metadata = {}

        try:
            cell_id = self.extension.cell.cell_id
        except AttributeError:
            cell_id = None

        revision.metadata['cell_id'] = cell_id

        return revision


class CellCodeAnnotator(Annotator):
    """"Annotates revisions with cell contents"""
    def annotate(self, revision):
        if self.extension.cell is not None:
            code = self.extension.cell.raw_cell
        else:
            code = "N/A"

        revision.data.append(revision.client.CodeData(name="Jupyter Cell",
                                                      language=CodeLanguage.PYTHON,
                                                      contents=code))
        return revision


class PipFreezeAnnotator(Annotator):
    """Annotates revisions with the output of pip freeze"""
    def __init__(self, extension, cache=True):
        """\
        :param extension: the GoFigr Jupyter extension
        :param cache: if True, will only run pip freeze once and cache the output
        """
        super().__init__(extension)
        self.cache = cache
        self.cached_output = None

    def annotate(self, revision):
        if self.cache and self.cached_output:
            output = self.cached_output
        else:
            try:
                output = subprocess.check_output(["pip", "freeze"]).decode('ascii')
                self.cached_output = output
            except subprocess.CalledProcessError as e:
                output = e.output

        revision.data.append(revision.client.TextData(name="pip freeze", contents=output))
        return revision


class SystemAnnotator(Annotator):
    """Annotates revisions with the OS version"""
    def annotate(self, revision):
        try:
            output = subprocess.check_output(["uname", "-a"]).decode('ascii')
        except subprocess.CalledProcessError as e:
            output = e.output

        revision.data.append(revision.client.TextData(name="System Info", contents=output))
        return revision


NOTEBOOK_PATH = "notebook_path"
NOTEBOOK_NAME = "notebook_name"
NOTEBOOK_URL = "url"
NOTEBOOK_KERNEL = "kernel"
PYTHON_VERSION = "python_version"


class NotebookMetadataAnnotator(Annotator):
    """"Annotates revisions with notebook metadata, including filename & path, as well as the full URL"""

    def parse_metadata(self):
        """Infers the notebook path & name from metadata passed through the WebSocket (if available)"""
        meta = self.extension.notebook_metadata
        if meta is None:
            raise RuntimeError("No Notebook metadata available")
        if 'url' not in meta:
            raise RuntimeError("No URL found in Notebook metadata")

        notebook_name = unquote(urlparse(meta['url']).path.rsplit('/', 1)[-1])
        notebook_dir = self.extension.shell.starting_dir
        full_path = os.path.join(notebook_dir, notebook_name)

        if not os.path.exists(full_path):
            print(f"The inferred path for the notebook does not exist: {full_path}. {PATH_WARNING}", file=sys.stderr)

        return {NOTEBOOK_PATH: full_path,
                NOTEBOOK_NAME: notebook_name,
                NOTEBOOK_URL: meta.get('url')}

    def annotate(self, revision):
        if revision.metadata is None:
            revision.metadata = {}

        try:
            if NOTEBOOK_NAME not in revision.metadata or NOTEBOOK_PATH not in revision.metadata:
                revision.metadata.update(self.parse_metadata())
        except Exception:  # pylint: disable=broad-exception-caught
            print(f"GoFigr could not automatically obtain the name of the currently"
                  f" running notebook. {PATH_WARNING}",
                  file=sys.stderr)

            revision.metadata[NOTEBOOK_NAME] = "N/A"
            revision.metadata[NOTEBOOK_PATH] = "N/A"

        return revision


class NotebookNameAnnotator(NotebookMetadataAnnotator):
    """(Deprecated) Annotates revisions with notebook name & path"""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        print("NotebookNameAnnotator is deprecated. Please use NotebookMetadataAnnotator", file=sys.stderr)


class EnvironmentAnnotator(Annotator):
    """Annotates revisions with the python version & the kernel info"""
    def annotate(self, revision):
        if revision.metadata is None:
            revision.metadata = {}

        revision.metadata[NOTEBOOK_KERNEL] = sys.executable
        revision.metadata[PYTHON_VERSION] = sys.version

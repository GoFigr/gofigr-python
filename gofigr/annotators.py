"""\
Copyright (c) 2023, Flagstaff Solutions, LLC
All rights reserved.

"""
import os
import subprocess
import sys
from abc import ABC
from urllib.parse import unquote, urlparse

import ipynbname

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


class NotebookNameAnnotator(Annotator):
    """"Annotates revisions with the name & path of the current notebook"""
    def infer_from_metadata(self):
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

        return full_path, notebook_name

    def annotate(self, revision):
        if revision.metadata is None:
            revision.metadata = {}

        try:
            if 'notebook_name' not in revision.metadata:
                revision.metadata['notebook_name'] = ipynbname.name()
            if 'notebook_path' not in revision.metadata:
                revision.metadata['notebook_path'] = str(ipynbname.path())

        except Exception:  # pylint: disable=broad-exception-caught
            try:
                revision.metadata['notebook_path'], revision.metadata['notebook_name'] = self.infer_from_metadata()
            except Exception:  # pylint: disable=broad-exception-caught
                print(f"GoFigr could not automatically obtain the name of the currently"
                      f" running notebook. {PATH_WARNING}",
                      file=sys.stderr)

                revision.metadata['notebook_name'] = "N/A"
                revision.metadata['notebook_path'] = "N/A"

        return revision

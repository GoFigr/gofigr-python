"""\
Copyright (c) 2023, Flagstaff Solutions, LLC
All rights reserved.

"""
import json
import logging
import os
import re
import subprocess
import sys
from abc import ABC
from urllib.parse import unquote, urlparse

import git
from IPython import get_ipython

from gofigr.models import CodeLanguage
from gofigr.databricks import get_dbutils

PATH_WARNING = "To fix this warning, you can manually specify the notebook name & path in the call to configure(). " \
               "Please see https://gofigr.io/docs/gofigr-python/latest/customization.html#notebook-name-path " \
               "for details."


class Annotator(ABC):
    """\
    Annotates figure revisions with pertinent information, such as cell code, variable values, etc.

    """
    def annotate(self, revision):
        """\
        Annotates a figure revision in-place.

        :param revision: revision to annotate
        :return: annotated revision (same object as input).

        """
        raise NotImplementedError("Must be implemented in subclass")


class IPythonAnnotator(Annotator):
    """\
    Annotates figures within the IPython/Jupyter environment.

    """
    def get_ip_extension(self):
        """\
        :return: IPython extension if available, None otherwise.

        """
        from gofigr.jupyter import get_extension  # pylint: disable=import-outside-toplevel
        try:
            return get_extension()
        except Exception as e:  # pylint: disable=broad-exception-caught
            logging.debug(f"IPython extension could not be found: {e}")
            return None

    def annotate(self, revision):
        """
        Annotates the figure revision.

        :param revision: FigureRevision
        :return: annotated FigureRevision

        """
        ext = self.get_ip_extension()
        if ext is None:
            return revision
        else:
            return self.annotate_ip(revision, ext)

    def annotate_ip(self, revision, ext):
        """\
        Annotates the figure revision assuming the IPython extension is available.

        :param revision: GoFigr revision
        :param ext: Jupyter extension
        :return: annotated revision
        """
        raise NotImplementedError("Must be implemented in subclass")


class CellIdAnnotator(IPythonAnnotator):
    """Annotates revisions with the ID of the Jupyter cell"""
    def annotate_ip(self, revision, ext):
        if revision.metadata is None:
            revision.metadata = {}

        try:
            cell_id = ext.cell.cell_id
        except AttributeError as e:
            logging.debug(e)
            cell_id = None

        revision.metadata['cell_id'] = cell_id

        return revision


class CellCodeAnnotator(IPythonAnnotator):
    """Annotates revisions with cell contents"""
    def annotate_ip(self, revision, ext):
        if ext.cell is not None:
            code = ext.cell.raw_cell
        else:
            code = "N/A"

        revision.data.append(revision.client.CodeData(name="Jupyter Cell",
                                                      language=CodeLanguage.PYTHON,
                                                      contents=code))
        return revision


class PipFreezeAnnotator(Annotator):
    """Annotates revisions with the output of pip freeze"""
    def __init__(self, cache=True):
        """\
        :param cache: if True, will only run pip freeze once and cache the output
        """
        super().__init__()
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


class ScriptAnnotator(Annotator):
    """Annotates revisions with the code of the running script"""
    def annotate(self, revision):
        if get_ipython() is not None:  # skip if running interactively
            return revision

        if os.path.exists(sys.argv[0]):
            revision.data.append(revision.client.FileData.read(sys.argv[0]))

        if revision.metadata is None:
            revision.metadata = {}

        revision.metadata['argv'] = list(sys.argv)
        return revision


class GitAnnotator(Annotator):
    """Annotates revisions with Git information"""

    def annotate(self, revision):
        """
        Generates a link for the current commit of a local repository.
        """
        try:
            # 1. Initialize the repository object
            repo = git.Repo(".", search_parent_directories=True)

            try:
                branch_name = repo.active_branch.name
            except TypeError:
                branch_name = "Detached HEAD"

            # 2. Get the current commit hash
            commit_hash = repo.head.commit.hexsha

            # 3. Get the URL of the 'origin' remote
            remote_url = repo.remotes.origin.url

            # 4. Clean and reformat the remote URL to a standard HTTPS format
            #    Handles both SSH (git@github.com:user/repo.git) and HTTPS formats
            http_url = re.sub(r'\.git$', '', remote_url)  # Remove .git suffix
            if http_url.startswith('git@'):
                # Convert SSH URL to HTTPS
                http_url = http_url.replace(':', '/').replace('git@', 'https://', 1)

            # 5. Construct the final commit link
            if 'github.com' in http_url.lower():
                commit_link = f"{http_url}/commit/{commit_hash}"
            elif 'bitbucket.org' in http_url.lower():
                commit_link = f"{http_url}/commits/{commit_hash}"
            else:
                commit_link = None

            revision.metadata['git'] = {'branch': branch_name,
                                        'hash': commit_hash,
                                        'remote_url': remote_url,
                                        'commit_link': commit_link}

        except git.exc.InvalidGitRepositoryError:
            logging.debug("Error: Not a valid git repository.")
        except Exception as e:  # pylint: disable=broad-exception-caught
            logging.debug(f"An unexpected error occurred: {e}")
            return None

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
BACKEND_NAME = "backend"


_ACTIVE_TAB_TITLE = "active_tab_title"


def _parse_path_from_tab_title(title):
    """Parses out the notebook path from the tab/widget title"""
    for line in title.splitlines(keepends=False):
        m = re.match(r'Path:\s*(.*)\s*', line)
        if m:
            return m.group(1)
    return None


class NotebookMetadataAnnotator(IPythonAnnotator):
    """Annotates revisions with notebook metadata, including filename & path, as well as the full URL"""
    def parse_from_databricks(self):
        """Returns notebook path if running in Databricks"""
        try:
            # pylint: disable=undefined-variable
            context = get_dbutils(get_ipython()).notebook.entry_point.getDbutils().notebook().getContext()
            nb = context.notebookPath().get()
            return {NOTEBOOK_PATH: nb, NOTEBOOK_NAME: os.path.basename(nb)}
        except Exception as e:  # pylint: disable=broad-exception-caught
            logging.debug(f"Unable to parse notebook metadata from Databricks: {e}")
            return None

    def parse_from_vscode(self):
        """Returns notebook path if running in VSCode"""
        ext = self.get_ip_extension()
        if ext is None:
            return None

        try:
            if ext.cell is None or getattr(ext.cell, "cell_id") is None:
                return None
            elif "vscode-notebook-cell:" not in ext.cell.cell_id:
                return None

            m = re.match(r'^vscode-notebook-cell:(.*)#.*$', unquote(ext.cell.cell_id))
            if m is None:
                return None

            notebook_path = m.group(1)
            notebook_name = os.path.basename(notebook_path)

            return {NOTEBOOK_PATH: notebook_path,
                    NOTEBOOK_NAME: notebook_name}
        except Exception:  # pylint: disable=broad-exception-caught
            return None

    def try_get_metadata(self):
        """Infers the notebook path & name using currently available metadata if possible, returning None otherwise"""
        try:
            return self.parse_metadata(error=False)
        except Exception:  # pylint: disable=broad-exception-caught
            return None

    def _parse_from_proxy(self, meta, error):
        if 'url' not in meta and _ACTIVE_TAB_TITLE not in meta:
            if error:
                raise RuntimeError("No URL found in Notebook metadata")
            else:
                return None

        notebook_name = None

        # Try parsing the name from the title first
        if _ACTIVE_TAB_TITLE in meta and meta[_ACTIVE_TAB_TITLE] is not None:
            notebook_name = _parse_path_from_tab_title(meta[_ACTIVE_TAB_TITLE])

        # If that doesn't work, try the URL
        if notebook_name is None:
            notebook_name = unquote(urlparse(meta['url']).path.rsplit('/', 1)[-1])

        notebook_dir = get_ipython().starting_dir
        full_path = None

        for candidate_path in [os.path.join(notebook_dir, notebook_name),
                               os.path.join(notebook_dir, os.path.basename(notebook_name)),
                               os.path.join(os.path.dirname(notebook_dir), notebook_name),
                               os.path.join(os.path.dirname(notebook_dir), os.path.basename(notebook_name))]:
            if os.path.exists(candidate_path):
                full_path = candidate_path
                break

        if full_path is None:
            full_path = os.path.join(notebook_dir, notebook_name)  # might still be helpful, even if slightly incorrect
            print(f"The inferred path for the notebook does not exist: {full_path}. {PATH_WARNING}", file=sys.stderr)

        return {NOTEBOOK_PATH: full_path,
                NOTEBOOK_NAME: notebook_name,
                NOTEBOOK_URL: meta.get('url')}

    def parse_metadata(self, error=True):
        """
        Infers the notebook path & name from metadata passed through the WebSocket (if available)

        :param revision: GoFigr Revision instance
        :param error: if True, will raise an error if metadata is not available
        """
        vsc_meta = self.parse_from_vscode()
        if vsc_meta is not None:
            return vsc_meta

        db_meta = self.parse_from_databricks()
        if db_meta is not None:
            return db_meta

        # At this point the metadata needs to come from the JavaScript proxy
        ext = self.get_ip_extension()
        meta = ext.notebook_metadata if ext is not None else None
        if meta is None and error:
            raise RuntimeError("No Notebook metadata available")
        elif meta is None:
            return None

        return self._parse_from_proxy(meta, error)

    def annotate(self, revision):
        if revision.metadata is None:
            revision.metadata = {}

        try:
            if NOTEBOOK_NAME not in revision.metadata or NOTEBOOK_PATH not in revision.metadata:
                revision.metadata.update(self.parse_metadata())

            full_path = revision.metadata.get(NOTEBOOK_PATH)
            if full_path and os.path.exists(full_path):
                revision.client.sync.sync(full_path)

        except Exception as e:  # pylint: disable=broad-exception-caught
            print(f"GoFigr could not automatically obtain the name of the currently"
                  f" running notebook. {PATH_WARNING} Details: {e}",
                  file=sys.stderr)

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

        return revision


class BackendAnnotator(Annotator):
    """Annotates revisions with the python version & the kernel info"""
    def annotate(self, revision):
        if revision.metadata is None:
            revision.metadata = {}

        revision.metadata[BACKEND_NAME] = revision.backend.get_backend_name() if revision.backend is not None else "N/A"
        return revision


class HistoryAnnotator(Annotator):
    """Annotates revisions with IPython execution history"""
    def annotate(self, revision):
        ip = get_ipython()

        if not hasattr(ip, 'history_manager'):
            return revision

        hist = ip.history_manager
        if hist is None:
            return revision

        revision.data.append(revision.client.CodeData(name="IPython history",
                                                      language="python",
                                                      format="jupyter-history/json",
                                                      contents=json.dumps(hist.input_hist_raw)))
        return revision

"""\
Copyright (c) 2025, Flagstaff Solutions, LLC
All rights reserved.

"""
import json
import sys

from IPython import get_ipython

try:
    from databricks.sdk import WorkspaceClient
except ImportError:
    pass

def get_dbutils(shell=None):
    """Gets dbutils if running on DataBricks"""
    if shell is None:
        shell = get_ipython()

    return shell.user_ns.get('dbutils') if shell is not None else None

def is_databricks_environment():
    """True if running on Databricks"""
    return get_dbutils() is not None

def get_workspace_client():
    """Gets a WorkspaceClient if running on Databricks"""
    dbutils = get_dbutils()
    if dbutils is None:
        raise ValueError("dbutils not available. Are you sure you are running on Databricks?")

    databricks_url = dbutils.notebook.entry_point.getDbutils().notebook().getContext().apiUrl().getOrElse(None)
    token = dbutils.notebook.entry_point.getDbutils().notebook().getContext().apiToken().getOrElse(None)
    return WorkspaceClient(host=databricks_url, token=token)

def save_config(config):
    """Saves the GoFigr configuration in the databricks secret manager"""
    w = get_workspace_client()
    if not any(scope.name == "gofigr" for scope in w.secrets.list_scopes()):
        w.secrets.create_scope("gofigr")

    w.secrets.put_secret("gofigr", "config", string_value=json.dumps(config))

def get_config():
    """Gets the GoFigr config from the Databricks secret manager"""
    dbutils = get_dbutils()
    if dbutils is None:
        return None

    try:
        return json.loads(dbutils.secrets.get("gofigr", "config"))
    except Exception as e:  # pylint: disable=broad-exception-caught
        print(f"Failed to get config from DataBricks: {str(e)}", file=sys.stderr)
        return None

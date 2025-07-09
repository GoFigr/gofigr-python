"""\
Copyright (c) 2024, Flagstaff Solutions, LLC
All rights reserved.

"""
import inspect
import json
import logging
import os
import uuid
from base64 import b64encode
from importlib import resources

import six

from gofigr.databricks import get_config as get_databricks_config


def read_resource_text(package, resource):
    """\
    Reads a resource and returns it as a base-64 encoded string.

    :param package: package name
    :param resource: resource name
    :return: resource contents as a string

    """
    # pylint: disable=deprecated-method
    with resources.open_text(package, resource) as f:
        return f.read()


def read_resource_b64(package, resource):
    """\
    Reads a resource and returns it as a base-64 encoded string.

    :param package: package name
    :param resource: resource name
    :return: base64-encoded string

    """
    # pylint: disable=deprecated-method
    with resources.open_binary(package, resource) as f:
        return b64encode(f.read()).decode('ascii')


def from_config_or_env(env_prefix, config_path):
    """\
    Decorator that binds function arguments in order of priority (most important first):
    1. args/kwargs
    2. environment variables
    3. vendor-specific secret manager
    4. config file
    5. function defaults

    :param env_prefix: prefix for environment variables. Variables are assumed to be named \
    `<prefix> + <name of function argument in all caps>`, e.g. if prefix is ``MYAPP`` and function argument \
    is called host_name, we'll look for an \
    environment variable named ``MYAPP_HOST_NAME``.
    :param config_path: path to the JSON config file. If a list, will be checked in order until one is found.
    Function arguments will be looked up using their verbatim names.
    :return: decorated function

    """
    def decorator(func):
        @six.wraps(func)
        def wrapper(*args, **kwargs):
            # Read config file, if it exists
            if config_path and os.path.exists(config_path):
                logging.debug("Loading config from %s", config_path)
                with open(config_path, 'r', encoding='utf-8') as f:
                    try:
                        config_file = json.load(f)
                    except Exception as e:
                        raise RuntimeError(f"Error parsing configuration file {config_path}") from e
            else:
                config_file = {}

            dbconfig = get_databricks_config() or {}

            sig = inspect.signature(func)
            param_values = sig.bind_partial(*args, **kwargs).arguments
            for param_name in sig.parameters:
                env_name = f'{env_prefix}{param_name.upper()}'
                if param_name in param_values:
                    continue  # value supplied through args/kwargs: ignore env variables and the config file.
                elif env_name in os.environ:
                    param_values[param_name] = os.environ[env_name]
                elif param_name in dbconfig:
                    param_values[param_name] = dbconfig[param_name]
                elif param_name in config_file:
                    param_values[param_name] = config_file[param_name]

            return func(**param_values)

        return wrapper

    return decorator


def try_parse_uuid4(text):
    """Tries to parse a UUID from a string, returning it if successful, or returning None if not."""
    if text is None:
        return None

    try:
        return str(uuid.UUID(text, version=4))
    except Exception:  # pylint: disable=broad-exception-caught
        return None

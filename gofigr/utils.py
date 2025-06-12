"""\
Copyright (c) 2024, Flagstaff Solutions, LLC
All rights reserved.

"""
import inspect
import json
import os
from base64 import b64encode
from importlib import resources

import six

import gofigr.databricks


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

            dbconfig = gofigr.databricks.get_config() or {}

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

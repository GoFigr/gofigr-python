"""\
Copyright (c) 2024, Flagstaff Solutions, LLC
All rights reserved.

"""
from base64 import b64encode
from importlib import resources



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

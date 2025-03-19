"""\
Copyright (c) 2023, Flagstaff Solutions, LLC
All rights reserved.

"""
import getpass
import json
import os
import sys
from argparse import ArgumentParser

from gofigr import API_URL, GoFigr, WorkspaceType


def read_input(prompt, validator, default=None, password=False):
    """\
    Prompts the user for input.

    :param prompt: Prompt, e.g. "Username: "
    :param validator: callable which validates and optionally parses the input. The prompt will be repeated until we
    get valid input.
    :param default: default value
    :param password: if True, will read a password without echoing
    :return: result of validator() on the input

    """
    sys.stdout.write(prompt)
    sys.stdout.flush()

    if password:
        val = getpass.getpass("")
    else:
        val = sys.stdin.readline().strip()

    try:
        if val == "" and default is not None:
            return validator(default)
        else:
            return validator(val)
    except ValueError as e:
        print(f"{e}. Please try again.")
        return read_input(prompt, validator, default, password)


def assert_nonempty(val):
    """\
    Asserts that a value is non-empty: not None and not all whitespace

    :param val: value to check
    :return: input value if it passes all checks, or raise ValueError otherwise

    """
    if val is None or val.strip() == "":
        raise ValueError("Empty input")
    else:
        return val


def yes_no(val):
    """\
    Asserts that a value is "yes", "no", "y" or "n" (case-insensitive)

    :param val: value to check
    :return: True (for yes/y), False (for no/n), or ValueError otherwise

    """
    assert_nonempty(val)
    val = val.lower()
    if val not in ['yes', 'no', 'y', 'n']:
        raise ValueError("Please enter Yes/Y or No/N")
    return val in ['yes', 'y']


def valid_json(val):
    """\
    Checks that a value is valid JSON and parses it.

    :param val: value to check
    :return: parsed JSON or ValueError.

    """
    return json.loads(val)


def integer_range(min_val, max_val):
    """\
    Constructs a validator for a valid integer between min_val and max_val (inclusive)

    :param min_val: minimum acceptable value
    :param max_val: maximum acceptable value
    :return:
    """
    def _validate(val):
        num = int(val)
        if num < min_val or num > max_val:
            raise ValueError(f"Value must be in range {min_val} - {max_val}")
        else:
            return num

    return _validate

def pretty_format_name(name):
    """\
    Pretty formats a name as N/A if it's None.

    :param name: name to pretty format
    :return: name if it's not empty, or "N/A" otherwise.

    """
    if name is None:
        return 'N/A'
    else:
        return name


def login_with_username(config):
    """Logs in with a username and a password, returning a connected GoFigr client"""
    while True:
        username = read_input("Username: ", assert_nonempty)
        password = read_input("Password: ", assert_nonempty, password=True)

        print("Verifying connection...")
        try:
            gf = GoFigr(username=username, password=password, **config)
            gf.heartbeat(throw_exception=True)
            print("  => Authenticated successfully")
            return gf
        except RuntimeError as e:
            print(f"{e}. Please try again.")


def login_with_api_key(gf, config, config_path):
    """Using a GoFigr instance connected with a username and a password, switches to API key authentication"""
    while True:
        token = read_input("API key (leave blank to generate a new key): ", validator=lambda val: val)
        if token in [None, ""]:
            key_name = read_input("Key name: ", assert_nonempty)
            apikey = gf.create_api_key(key_name)
            print(f"  => Your new API key will be saved to {config_path}")
            config['api_key'] = apikey.token
        else:
            config['api_key'] = token

        # Connect with the API key
        try:
            gf_key = GoFigr(**config)
            gf_key.heartbeat(throw_exception=True)
            print("  => Connected successfully")
            return gf_key
        except RuntimeError as e:
            print(f"{e}. Please try again.")


def main():
    """\
    Main entry point
    """
    parser = ArgumentParser(prog="gfconfig",
                            description="Configures default settings for GoFigr.io")
    parser.add_argument("-a", "--advanced", action='store_true', help="Configure lesser-used settings.")
    args = parser.parse_args()

    config_path = os.path.join(os.environ['HOME'], '.gofigr')

    print("-" * 30)
    print("GoFigr configuration")
    print("-" * 30)

    config = {}
    if args.advanced:
        config['url'] = read_input(f"API URL [{API_URL}]: ", assert_nonempty, default=API_URL)

    # Log in with username + pw first
    gf_pw_auth = login_with_username(config)

    # Switch to API key auth
    gf = login_with_api_key(gf_pw_auth, config, config_path)

    if args.advanced:
        config['auto_publish'] = read_input("Auto-publish all figures [Y/n]: ", yes_no, default='yes')
        config['default_metadata'] = read_input("Default revision metadata (JSON): ", valid_json, default="null")

    workspaces = gf.workspaces
    print("\nPlease select a default workspace: ")
    default_idx = 1
    for idx, wx in enumerate(workspaces, 1):
        pp_name = pretty_format_name(wx.name)
        pp_description = pretty_format_name(wx.description)

        print(f"  [{idx:2d}] - {pp_name:30s} - {pp_description:30s} - API ID: {wx.api_id}")
        if wx.workspace_type == WorkspaceType.PRIMARY:
            default_idx = idx

    workspace_idx = read_input(f"Selection [{default_idx}]: ",
                               validator=integer_range(1, len(workspaces)),
                               default=default_idx)
    config['workspace'] = workspaces[workspace_idx - 1].api_id

    with open(config_path, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=4)
        f.write("\n")

    print(f"\nConfiguration saved to {config_path}. Happy analysis!")

"""\
Copyright (c) 2023, Flagstaff Solutions, LLC
All rights reserved.

"""
import getpass
import json
import os
import sys
import time
import webbrowser
from argparse import ArgumentParser
from collections import namedtuple

import requests

from gofigr import API_URL, GoFigr, WorkspaceType
import gofigr.databricks as db

Auth0Config = namedtuple('Auth0Config', ['domain', 'client_id', 'audience'])

def get_auth0_config(api_url):
    """Fetch Auth0 configuration from the server's /info endpoint.
    Returns an Auth0Config or None if unavailable."""
    try:
        resp = requests.get(f"{api_url}/api/v1.4/info/", timeout=5)
        resp.raise_for_status()
        data = resp.json()
        domain = data.get('auth0_domain')
        client_id = data.get('auth0_cli_client_id')
        audience = data.get('auth0_audience', '')
        if domain and client_id:
            return Auth0Config(domain=domain, client_id=client_id, audience=audience)
    except (requests.RequestException, ValueError, KeyError):
        pass
    return None


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
        val = input("").strip()

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


def resolve_config_path(path_arg):
    """\
    Resolves the config file path from a command-line argument.

    If the argument is a directory (exists as a directory or ends with /),
    appends '.gofigr' as the filename.
    If it's a file path, uses it directly.
    Creates parent directories if they don't exist.

    :param path_arg: Either a directory path or a full file path
    :return: Full path to the config file
    """
    if path_arg is None:
        return os.path.join(os.environ['HOME'], '.gofigr')

    path_arg = os.path.expanduser(path_arg)  # Handle ~ in paths

    # Normalize trailing slashes
    path_arg = path_arg.rstrip(os.sep)

    # Check if it's an existing directory
    if os.path.isdir(path_arg):
        return os.path.join(path_arg, '.gofigr')

    # Check if parent directory exists and create it if needed
    parent_dir = os.path.dirname(path_arg)
    if parent_dir and not os.path.exists(parent_dir):
        # Create parent directories if needed
        os.makedirs(parent_dir, exist_ok=True)

    # Treat as file path (will be created when written)
    return path_arg

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


def login_with_device_flow(config, auth0_config):
    """Logs in via Auth0 Device Authorization Flow, returning a connected GoFigr client"""
    # Request device code
    resp = requests.post(f"https://{auth0_config.domain}/oauth/device/code", json={
        'client_id': auth0_config.client_id,
        'audience': auth0_config.audience,
        'scope': 'openid email profile',
    }, timeout=10)
    if not resp.ok:
        error_detail = resp.json().get('error_description', resp.text) if resp.text else resp.reason
        raise RuntimeError(f"Failed to start device authorization (HTTP {resp.status_code}): {error_detail}")
    data = resp.json()

    verification_uri = data.get('verification_uri_complete', data['verification_uri'])
    user_code = data['user_code']
    device_code = data['device_code']
    interval = data.get('interval', 5)

    print("\n  To log in, open this URL in your browser:\n")
    print(f"    {verification_uri}\n")
    print(f"  And enter code: {user_code}\n")

    try:
        webbrowser.open(verification_uri)
        print("  (Browser opened automatically)")
    except webbrowser.Error:
        pass

    print("  Waiting for authorization...", end='', flush=True)

    # Poll for token
    while True:
        time.sleep(interval)
        token_resp = requests.post(f"https://{auth0_config.domain}/oauth/token", json={
            'grant_type': 'urn:ietf:params:oauth:grant-type:device_code',
            'client_id': auth0_config.client_id,
            'device_code': device_code,
        }, timeout=10)

        token_data = token_resp.json()

        if token_resp.ok:
            print(" done!")
            access_token = token_data['access_token']

            # Create a GoFigr client using the Auth0 token
            gf = GoFigr(authenticate=False, **config)
            gf.set_access_token(access_token)
            gf.username = gf.user_info().username
            print("  => Authenticated successfully")
            return gf

        error = token_data.get('error')
        if error == 'authorization_pending':
            print('.', end='', flush=True)
            continue
        elif error == 'slow_down':
            interval += 1
            continue
        elif error == 'expired_token':
            print("\n  Authorization timed out. Please try again.")
            raise RuntimeError("Device authorization expired")
        elif error == 'access_denied':
            print("\n  Authorization was denied.")
            raise RuntimeError("Device authorization denied")
        else:
            raise RuntimeError(f"Device flow error: {token_data.get('error_description', error)}")


def login_with_api_key(gf, config, config_path):
    """Using a GoFigr instance connected with a username and a password, switches to API key authentication"""
    while True:
        token = read_input("Paste an existing API key, or press Enter to generate a new one: ",
                          validator=lambda val: val)
        if token in [None, ""]:
            key_name = read_input("Key name: ", assert_nonempty)
            apikey = gf.create_api_key(key_name)
            if not db.is_databricks_environment():
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


def gfconfig():
    """Convenience when calling directly from Python"""
    return main(args=[])


def main(args=None):
    """\
    Main entry point
    """
    parser = ArgumentParser(prog="gfconfig",
                            description="Configures default settings for GoFigr.io")
    parser.add_argument("-a", "--advanced", action='store_true', help="Configure lesser-used settings.")
    parser.add_argument("-c", "--config-path", dest="config_path", default=None,
                        help="Path where to save the .gofigr config file. "
                             "Can be a directory (will append .gofigr) or a full file path. "
                             "Default: ~/.gofigr")
    parser.add_argument("--url", default=None,
                        help=f"API URL. Default: {API_URL}")
    args = parser.parse_args(args)

    config_path = resolve_config_path(args.config_path)

    print("-" * 30)
    print("GoFigr configuration")
    print("-" * 30)

    config = {'api_key': None, 'url': args.url or API_URL}
    if args.advanced and not args.url:
        config['url'] = read_input(f"API URL [{API_URL}]: ", assert_nonempty, default=API_URL)

    # Authenticate via Auth0 Device Code flow
    auth0_config = get_auth0_config(config['url'])
    if not auth0_config:
        print(f"Error: Could not fetch Auth0 configuration from {config['url']}/api/v1.4/info/")
        print("Please check the URL and try again.")
        sys.exit(1)
    gf_auth = login_with_device_flow(config, auth0_config)

    # Switch to API key auth
    gf = login_with_api_key(gf_auth, config, config_path)

    if args.advanced:
        config['auto_configure'] = read_input("Auto-configure on extension load [Y/n]: ", yes_no, default='yes')
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

    if db.is_databricks_environment():
        db.save_config(config)
        print("\nConfiguration saved in Databricks under the gofigr secret scope. Happy analysis!")
    else:
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=4)
            f.write("\n")

        print(f"\nConfiguration saved to {config_path}. Happy analysis!")

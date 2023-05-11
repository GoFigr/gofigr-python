"""\
Copyright (c) 2022, Flagstaff Solutions, LLC
All rights reserved.

"""
from json import dumps as json_dumps
import logging

import requests
from requests import Session

from gofigr.models import *

LOGGER = logging.getLogger(__name__)

API_URL = "https://api.gofigr.io"
API_VERSION = "v1"

APP_URL = "https://app.gofigr.io"


def assert_one(elements, error_none=None, error_many=None):
    """\
    Asserts that a list/tuple contains only a single element (raising an exception if not), and returns
    that element.

    :param elements: list/tuple
    :param error_none: error message if input is empty
    :param error_many: error message if multiple elements are present
    :return: the single element in the input
    """
    if len(elements) == 0:
        raise ValueError(error_none or "Expected exactly one value but got none")
    elif len(elements) > 1:
        raise ValueError(error_many or f"Expected exactly one value but got n={len(elements)}")
    else:
        return elements[0]


class UnauthorizedError(RuntimeError):
    """\
    Thrown if user doesn't have permissions to perform an action.
    """
    pass


class UserInfo:
    """\
    Stores basic information about a user: username, email, etc.

    """
    def __init__(self, username, first_name, last_name, email, date_joined, is_active, avatar):
        """\

        :param username:
        :param first_name:
        :param last_name:
        :param email:
        :param date_joined:
        :param is_active:
        :param avatar: avatar as a PIL.Image instance
        """
        self.username = username
        self.first_name, self.last_name = first_name, last_name
        self.email = email
        self.date_joined = date_joined
        self.is_active = is_active
        self.avatar = avatar

    @staticmethod
    def _avatar_to_b64(img):
        if not img:
            return None

        bio = io.BytesIO()
        img.save(bio, format="png")
        return b64encode(bio.getvalue()).decode('ascii')

    @staticmethod
    def _avatar_from_b64(data):
        if not data:
            return None

        return PIL.Image.open(io.BytesIO(b64decode(data)))

    @staticmethod
    def from_json(obj):
        """\
        Parses a UserInfo object from JSON

        :param obj: JSON representation
        :return: UserInfo instance
        """
        date_joined = obj.get('date_joined')
        return UserInfo(username=obj.get('username'),
                        first_name=obj.get('first_name'),
                        last_name=obj.get('last_name'),
                        email=obj.get('email'),
                        date_joined=dateutil.parser.parse(date_joined) if date_joined is not None else None,
                        is_active=obj.get('is_active'),
                        avatar=UserInfo._avatar_from_b64(obj.get('avatar')))

    def to_json(self):
        """Converts this UserInfo object to json"""
        return {'username': self.username,
                'first_name': self.first_name,
                'last_name': self.last_name,
                'email': self.email,
                'date_joined': str(self.date_joined) if self.date_joined else None,
                'is_active': self.is_active,
                'avatar': UserInfo._avatar_to_b64(self.avatar)}

    def __str__(self):
        return json_dumps(self.to_json())

    def __eq__(self, other):
        return str(self) == str(other)


class GoFigr:
    """\
    The GoFigr client. Handles all communication with the API: authentication, figure creation and manipulation,
    sharing, retrieval of user information, etc.

    """
    def __init__(self, username, password,
                 url=API_URL,
                 authenticate=True):
        """\

        :param username: username to connect with
        :param password: password for authentication
        :param url: API URL
        :param authenticate: whether to authenticate right away. If False, authentication will happen during
        the first request.

        """
        self.service_url = url
        self.username = username
        self.password = password

        self._primary_workspace = None

        self._access_token = None
        self._refresh_token = None

        if authenticate:
            self.authenticate()

        self._bind_models()

    @property
    def app_url(self):
        """Returns the URL to the GoFigr app"""
        return self.service_url.replace("api", "app")

    def _bind_models(self):
        """\
        Create instance-bound model classes, e.g. Workspace, Figure, etc. Each will internally
        store a reference to this GoFigr client -- that way we don't have to pass it around.

        :return: None
        """
        # pylint: disable=too-few-public-methods,protected-access
        for name, obj in globals().items():
            if inspect.isclass(obj) and issubclass(obj, ModelMixin):
                class _Bound(obj):
                    _gf = self

                _Bound.__qualname__ = f"GoFigr.{name}"
                _Bound._gofigr_type_name = name.replace("gf_", "")

                setattr(self, name.replace("gf_", ""), _Bound)
            elif inspect.isclass(obj) and issubclass(obj, NestedMixin):
                # Nested mixins don't reference the GoFigr object, but they're exposed in the same way
                # for consistency.
                setattr(self, name, obj)

    @property
    def api_url(self):
        """\
        Full URL to the API endpoint.
        """
        return f"{self.service_url}/api/{API_VERSION}/"

    @property
    def jwt_url(self):
        """\
        Full URL to the JWT endpoint (for authentication).
        """
        return f"{self.service_url}/api/token/"

    @staticmethod
    def _is_expired_token(response):
        """\
        Checks whether a response failed due to an expired auth token.

        :param response: Response object
        :return: True if failed due to an expired token, False otherwise.
        """
        if response.status_code != HTTPStatus.UNAUTHORIZED:
            return False
        try:
            obj = response.json()
            return obj.get('code') == 'token_not_valid'
        except ValueError:
            return False

    def _request(self, method, endpoint, throw_exception=True, expected_status=(HTTPStatus.OK, ), **kwargs):
        """\
        Convenience function for making HTTP requests.

        :param method: one of Session methods: Session.get, Session.post, etc.
        :param endpoint: relative API endpoint
        :param throw_exception: whether to check response status against expected_status and throw an exception
        :param expected_status: list of acceptable response status codes
        :param kwargs: extra params passed verbatim to method(...)
        :return: Response

        """
        url = urljoin(self.api_url, endpoint)
        if not hasattr(expected_status, '__iter__'):
            expected_status = [expected_status, ]

        if self._access_token is None:
            raise RuntimeError("Please authenticate first")

        rqst = requests.session()
        try:
            response = method(rqst, url, headers={'Authorization': f'Bearer {self._access_token}'}, **kwargs)
            if self._is_expired_token(response):
                self._refresh_access_token()
                return self._request(method, endpoint,
                                     throw_exception=throw_exception,
                                     expected_status=expected_status, **kwargs)

            if throw_exception and response.status_code not in expected_status:
                if response.status_code == HTTPStatus.FORBIDDEN:
                    raise UnauthorizedError(f"Unauthorized: {response.content}")
                else:
                    raise RuntimeError(f"Request to {url} returned {response.status_code}: {response.content}")

            return response
        finally:
            rqst.close()

    def _get(self, endpoint, throw_exception=True, **kwargs):
        return self._request(Session.get, endpoint, throw_exception=throw_exception, **kwargs)

    def _post(self, endpoint, json, throw_exception=True, **kwargs):
        return self._request(Session.post, endpoint, json=json, throw_exception=throw_exception, **kwargs)

    def _patch(self, endpoint, json, throw_exception=True, **kwargs):
        return self._request(Session.patch, endpoint, json=json, throw_exception=throw_exception, **kwargs)

    def _put(self, endpoint, json, throw_exception=True, **kwargs):
        return self._request(Session.put, endpoint, json=json, throw_exception=throw_exception, **kwargs)

    def _delete(self, endpoint, throw_exception=True, **kwargs):
        return self._request(Session.delete, endpoint, throw_exception=throw_exception,
                             expected_status=HTTPStatus.NO_CONTENT, **kwargs)

    def heartbeat(self, throw_exception=True):
        """\
        Checks whether we can communicate with the API. Currently, this works by polling /api/v1/info.

        :param throw_exception: throw an exception if response code is not 200
        :return: Response

        """
        return self._get("info/", throw_exception=throw_exception)

    def _refresh_access_token(self):
        """\
        Refresh the JWT access token. If a refresh is not possible (e.g. the token has expired), will attempt
        to re-authenticate.

        :return: True if successful. Exception if not.
        """
        rqst = requests.session()
        try:
            rsp = rqst.post(self.jwt_url + "refresh/",
                            data={'refresh': self._refresh_token},
                            allow_redirects=False)

            if rsp.status_code == 200:
                self._access_token = rsp.json()['access']
                return True
            else:
                return self.authenticate()
        finally:
            if rqst is not None:
                rqst.close()

    def authenticate(self):
        """\
        Authenticates with the API.

        :return: True
        """
        rqst = requests.session()
        try:
            rsp = rqst.post(self.jwt_url,
                            data={'username': self.username, 'password': self.password},
                            allow_redirects=False)

            if rsp.status_code != 200:
                raise RuntimeError("Authentication failed")

            self._refresh_token = rsp.json()['refresh']
            self._access_token = rsp.json()['access']
            return True
        finally:
            if rqst is not None:
                rqst.close()

    def user_info(self, username=None):
        """\
        Retrieves information about a user.

        :param username: username. Set to None for self.
        :return: UserInfo object.

        """
        if not username:
            return UserInfo.from_json(self._get("user").json()[0])
        else:
            return UserInfo.from_json(self._get("user/" + username).json())

    def update_user_info(self, user_info, username=None):
        """\
        Updates user information for a user.

        :param user_info: UserInfo instance
        :param username: optional username. This is for testing only -- you will get an error if attempting \
        to update information for anybody other than yourself.
        :return: refreshed UserInfo from server

        """
        response = self._put("user/" + (username or user_info.username) + "/", user_info.to_json())
        return UserInfo.from_json(response.json())

    @property
    def workspaces(self):
        """Returns a list of all workspaces that the current user is a member of."""
        # pylint: disable=no-member
        return self.Workspace.list()

    @property
    def primary_workspace(self):
        """\
        Returns the primary workspace for this user.

        :return: Workspace instance

        """
        if self._primary_workspace is not None:
            return self._primary_workspace

        primaries = [w for w in self.workspaces if w.workspace_type == "primary"]
        pw = assert_one(primaries,
                        "No primary workspace found. Please contact support.",
                        "Multiple primary workspaces found. Please contact support.")

        self._primary_workspace = pw
        return self._primary_workspace


def load_ipython_extension(ip):
    """\
    Loads the Jupyter extension. Present here so that we can do "%load_ext gofigr" without having to refer
    to a subpackage.

    :param ip: IPython shell
    :return: None

    """
    # pylint: disable=import-outside-toplevel
    from gofigr.jupyter import _load_ipython_extension
    return _load_ipython_extension(ip)

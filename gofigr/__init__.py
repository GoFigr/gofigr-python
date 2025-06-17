"""\
Copyright (c) 2022, Flagstaff Solutions, LLC
All rights reserved.

"""
import contextlib
import inspect
import logging
import warnings
from json import dumps as json_dumps

import requests
from PIL import Image
from requests import Session

from gofigr.context import RevisionContext
from gofigr.exceptions import UnauthorizedError, MethodNotAllowedError
from gofigr.models import *
from gofigr.utils import from_config_or_env
from gofigr.widget import DatasetWidget

LOGGER = logging.getLogger(__name__)

API_URL = "https://api.gofigr.io"
API_VERSION = "v1.2"

APP_URL = "https://app.gofigr.io"

PANDAS_READERS = ["read_csv", "read_excel", "read_json", "read_html", "read_parquet", "read_feather",
                  "read_hdf", "read_pickle", "read_sas"]
REVISION_ATTR = "_gofigr_revision"


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


class UserInfo:
    """\
    Stores basic information about a user: username, email, etc.

    """
    def __init__(self, username, first_name, last_name, email, date_joined, is_active, avatar,
                 is_staff, user_profile):
        """\

        :param username:
        :param first_name:
        :param last_name:
        :param email:
        :param date_joined:
        :param is_active:
        :param avatar: avatar as a PIL.Image instance
        :param is_staff: whether the user is staff or not
        """
        self.username = username
        self.first_name, self.last_name = first_name, last_name
        self.email = email
        self.date_joined = date_joined
        self.is_active = is_active
        self.avatar = avatar
        self.is_staff = is_staff
        self.user_profile = user_profile

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

        return Image.open(io.BytesIO(b64decode(data)))

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
                        is_staff=obj.get('is_staff'),
                        user_profile=obj.get('user_profile', {}),
                        avatar=UserInfo._avatar_from_b64(obj.get('avatar')))

    def to_json(self):
        """Converts this UserInfo object to json"""
        return {'username': self.username,
                'first_name': self.first_name,
                'last_name': self.last_name,
                'email': self.email,
                'date_joined': str(self.date_joined) if self.date_joined else None,
                'is_active': self.is_active,
                'is_staff': self.is_staff,
                'user_profile': self.user_profile,
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

    @from_config_or_env("GF_", os.path.join(os.environ['HOME'], '.gofigr'))
    def __init__(self,
                 username=None,
                 password=None,
                 api_key=None,
                 url=API_URL,
                 authenticate=True,
                 workspace_id=None,
                 anonymous=False,
                 data_log=None):
        """\

        :param username: username to connect with
        :param password: password for authentication
        :param api_key: API key for authentication (specify instead of username & password)
        :param url: API URL
        :param authenticate: whether to authenticate right away. If False, authentication will happen during
        the first request.
        :param workspace_id: workspace ID to use for all requests. If None, will use the primary workspace.
        :param anonymous: True for anonymous access. Default False.
        :param data_log: log of datasets referenced by this instance

        """
        self.service_url = url
        self.username = username
        self.password = password
        self.api_key = api_key
        self.anonymous = anonymous
        self.workspace_id = workspace_id
        self.data_log = data_log if data_log is not None else dict()
        self._primary_workspace = None

        # Tokens for JWT authentication
        self._access_token = None
        self._refresh_token = None

        if authenticate:
            self.authenticate()

        self._bind_models()
        self._bind_readers()

        self._sync = None

    @property
    def sync(self):
        if not self._sync:
            self._sync = DatasetSync(self, data_log=self.data_log)

        return self._sync

    def open(self, *args, **kwargs):
        return self.sync.open(*args, **kwargs)

    @property
    def app_url(self):
        """Returns the URL to the GoFigr app"""
        return self.service_url.replace("api", "app").replace(":8000", ":5173")

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

                clean_name = name.replace("gf_", "")
                _Bound.__name__ = f"GoFigr.{clean_name}"
                _Bound.__qualname__ = f"GoFigr.{clean_name}"
                _Bound._gofigr_type_name = clean_name

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

    def create_api_key(self, name, expiry=None, workspace=None):
        """\
        Creates an API key

        :param name: name of the key to create
        :param expiry: expiration date. If None, the key will not expire.
        :param workspace: workspace for which the key is to be valid. If None, key will have access to the same
        workspaces as the user.
        :return: ApiKey instance

        """
        if expiry is not None and expiry.tzinfo is None:
            expiry = expiry.astimezone()

        # pylint: disable=no-member
        return self.ApiKey(name=name, expiry=expiry, workspace=workspace).create()

    def list_api_keys(self):
        """Lists all API keys"""
        # pylint: disable=no-member
        return self.ApiKey().list()

    def get_api_key(self, api_id):
        """Gets information about a specific API key"""
        # pylint: disable=no-member
        return self.ApiKey(api_id=api_id).fetch()

    def revoke_api_key(self, api_id):
        """Revokes an API key"""
        # pylint: disable=no-member
        if isinstance(api_id, str):
            return self.ApiKey(api_id=api_id).delete(delete=True)
        else:
            return api_id.delete(delete=True)

    def _request(self, method, endpoint, throw_exception=True, expected_status=(HTTPStatus.OK, ),
                 absolute_url=False, **kwargs):
        """\
        Convenience function for making HTTP requests.

        :param method: one of Session methods: Session.get, Session.post, etc.
        :param endpoint: relative API endpoint
        :param throw_exception: whether to check response status against expected_status and throw an exception
        :param expected_status: list of acceptable response status codes
        :param absolute_url: if False (default), interpret the endpoint relative to the API URL. Otherwise assume
        it's fully qualified.
        :param kwargs: extra params passed verbatim to method(...)
        :return: Response

        """
        # pylint: disable=too-many-branches
        if not absolute_url:
            url = urljoin(self.api_url, endpoint)
        else:
            url = endpoint

        if not hasattr(expected_status, '__iter__'):
            expected_status = [expected_status, ]

        if self._access_token is None and self.api_key is None and not self.anonymous:
            raise RuntimeError("Please authenticate first")

        rqst = requests.session()
        try:
            if self.anonymous:
                response = method(rqst, url, **kwargs)
            elif self.api_key is None:
                response = method(rqst, url, headers={'Authorization': f'Bearer {self._access_token}'}, **kwargs)
            else:
                response = method(rqst, url, headers={'Authorization': f'Token {self.api_key}'}, **kwargs)

            if self._is_expired_token(response):
                self._refresh_access_token()
                return self._request(method, endpoint,
                                     throw_exception=throw_exception,
                                     expected_status=expected_status, **kwargs)

            if throw_exception and response.status_code not in expected_status:
                if response.status_code == HTTPStatus.FORBIDDEN:
                    raise UnauthorizedError(f"Unauthorized: {response.content}")
                elif response.status_code == HTTPStatus.METHOD_NOT_ALLOWED:
                    raise MethodNotAllowedError(f"Method not allowed: {response.content}")
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

    def _authenticate_jwt(self):
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

    def authenticate(self):
        """\
        Authenticates with the API.

        :return: True
        """
        if self.anonymous:
            self.username = None
            return True
        elif self.api_key is not None:
            # With an API key there's no separate auth step, so we make sure everything works by querying user info
            info = self.user_info()
            self.username = info.username
            return True
        else:
            return self._authenticate_jwt()

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
    def organizations(self):
        """Returns a list of all organizations that the current user is a member of."""
        # pylint: disable=no-member
        return self.Organization.list()

    @property
    def primary_workspace(self):
        """\
        Returns the primary workspace for this user.

        :return: Workspace instance

        """
        if self._primary_workspace is not None:
            return self._primary_workspace

        primaries = [w for w in self.workspaces if w.workspace_type == "primary"]
        primaries = [w for w in primaries if any(wm.username == self.username \
                                                 and wm.membership_type == WorkspaceMembership.OWNER
                                                 for wm in w.get_members(unauthorized_error=False))]

        if self.api_key is not None and len(primaries) == 0:
            self._primary_workspace = None
            return self._primary_workspace

        pw = assert_one(primaries,
                        "No primary workspace found. Please contact support.",
                        "Multiple primary workspaces found. Please contact support.")

        self._primary_workspace = pw
        return self._primary_workspace

    def _bind_readers(self):
        for name in PANDAS_READERS:
            # Store name in closure scope
            (lambda bound_name: setattr(self, name, lambda *args, **kwargs: getattr(self.sync, bound_name)(*args, **kwargs)))(name)


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


class DatasetSync:
    def __init__(self, gf, workspace_id=None, data_log=None):
        self.gf = gf
        self.workspace_id = workspace_id or self.gf.primary_workspace.api_id
        self.data_log = data_log if data_log is not None else dict()
        self._bind_readers()

        logging.debug(f"Using workspace ID {self.workspace_id}")

    @property
    def revisions(self):
        return self.data_log.values()

    def clear_revisions(self):
        self.data_log.clear()

    def _new_dataset(self, pathlike):
        logging.debug(f"Creating new dataset for {pathlike}")
        ds = self.gf.Dataset(name=os.path.basename(pathlike), workspace=self.gf.Workspace(api_id=self.workspace_id))
        ds.create()
        logging.debug(f"Created dataset {ds.api_id}")
        return ds

    def _new_revision(self, pathlike):
        logging.debug("New revision detected. Syncing...")
        datasets = self.gf.Dataset.find_by_name(os.path.basename(pathlike))
        logging.debug(f"Found datasets: {datasets}")

        # First, figure out which dataset we're syncing to
        if len(datasets) == 0:
            ds = self._new_dataset(pathlike)
        elif len(datasets) == 1:
            ds = datasets[0]
        else:
            warnings.warn(f"Multiple datasets with the same name found. Defaulting to first: "
                          f"{[d.api_id for d in datasets]}")
            ds = datasets[0]

        logging.debug(f"Creating a new revision for dataset {ds.api_id} with path {pathlike}")

        # Now create the revision under the dataset
        rev = self.gf.DatasetRevision(dataset=ds,
                                      data=[self.gf.FileData.read(pathlike)]).create()
        return rev

    def _log(self, revision, is_new_revision=False):
        revision.is_new_revision = is_new_revision
        self.data_log[revision.api_id] = revision
        logging.debug(f"Logged revision {revision.api_id} for dataset {revision.dataset.api_id}")
        logging.debug(f"Current revision cache: {self.data_log.keys()}")
        return revision

    def sync(self, pathlike):
        # Grab the checksum
        logging.debug(f"Syncing {pathlike}")

        checksum = self._calc_checksum(pathlike)
        if checksum is None:
            warnings.warn(f"Unable to calculate checksum for {pathlike}. Skipping sync.")
            return None

        logging.debug(f"Calculated checksum for {pathlike}: {checksum}")

        # Check if we already have this dataset
        revisions = self.gf.DatasetRevision.find_by_hash(checksum, "blake3")

        if len(revisions) == 0:
            return self._log(self._new_revision(pathlike), is_new_revision=True)
        elif len(revisions) == 1:
            logging.debug(f"Found existing revision {revisions[0].api_id}")
            return self._log(revisions[0])
        else:
            logging.debug(f"Found existing revisions: {[rev.api_id for rev in revisions]}")
            warnings.warn(f"Multiple datasets with the same checksum found. Defaulting to first: "
                          f"{[d.api_id for d in revisions]}")
            return self._log(revisions[0])


    @contextlib.contextmanager
    def open_with_revision(self, pathlike, *args, **kwargs):
        io = None
        try:
            rev = self.sync(pathlike)
            if rev:
                logging.info(f"Dataset synced: {rev.app_url}")
                DatasetWidget().show(rev)

            io = open(pathlike, *args, **kwargs)
            yield io, rev
        finally:
            if io is not None and not io.closed:
                io.close()

    @contextlib.contextmanager
    def open(self, pathlike, *args, **kwargs):
        with self.open_with_revision(pathlike, *args, **kwargs) as (io, rev):
            yield io

    def _wrap_reader(self, func):
        def wrapper(pathlike, *args, **kwargs):
            logging.debug(f"Calling {func.__name__} for {pathlike}")
            with self.open_with_revision(pathlike, 'rb') as (f, rev):
                frame = func(f, *args, **kwargs)
                frame.attrs = {REVISION_ATTR: rev.api_id}
                return frame
        return wrapper

    def _calc_checksum(self, pathlike):
        try:
            path = os.fspath(pathlike)
            if os.path.exists(path):
                file_hasher = blake3(max_threads=blake3.AUTO)
                file_hasher.update_mmap(path)
                return file_hasher.hexdigest()
            else:
                warnings.warn(
                    "Non-local paths aren't supported yet. Please consider submitting an issue here: https://github.com/GoFigr/gofigr-python/issues")
                return None
        except TypeError:
            warnings.warn(
                "This type of input isn't supported yet. Please consider submitting an issue here: https://github.com/GoFigr/gofigr-python/issues")
            return None

    def _bind_readers(self):
        for name in PANDAS_READERS:
            setattr(self, name, self._wrap_reader(getattr(pd, name)))



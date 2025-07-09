"""\
Copyright (c) 2022, Flagstaff Solutions, LLC
All rights reserved.

"""
# Many of the properties here are defined dynamically based on Field specifications, so no-member isn't meaningful
# pylint: disable=no-member, protected-access

import abc
import io
import os
from base64 import b64encode, b64decode
from collections import namedtuple
from http import HTTPStatus
from urllib.parse import urljoin
from uuid import uuid4

import PIL
import dateutil.parser

import pandas as pd
from blake3 import blake3

from gofigr.exceptions import UnauthorizedError
from gofigr.profile import MeasureExecution


class Field:
    """\
    Describes a dynamically created object field, i.e. figure name, revision etc.

    """
    def __init__(self, name, parent=None, derived=False):
        """\

        :param name: name of the field as it will appear in the parent object, i.e. object.<name>
        :param parent: instance of the object containing the field
        :param derived: whether the field is derived. Derived fields are not included in REST API calls.

        """
        self.name = name
        self.parent = parent
        self.derived = derived

    def to_representation(self, value):
        """Converts the value of this field to a JSON-serializable primitive"""
        return value

    def to_internal_value(self, gf, data):  # pylint: disable=unused-argument
        """\
        Parses the value of this field from JSON primitives.

        :param gf: GoFigr instance
        :param data: parsed JSON primitives
        :return: parsed value

        """
        return data

    def clone(self):
        """\
        Creates a clone of this field.

        :return: cloned field
        """
        return Field(self.name, parent=self.parent, derived=self.derived)


class JSONField(Field):
    """\
    Represents a field that stores JSON primitives.
    """
    def to_representation(self, value):
        return value

    def to_internal_value(self, gf, data):
        # This function is called on the result of response.json() which would have already parsed
        # nested fields.
        return data

    def clone(self):
        return JSONField(self.name, parent=self.parent, derived=self.derived)


class Timestamp(Field):
    """\
    Timestamp field
    """
    def to_representation(self, value):
        return str(value) if value is not None else None

    def to_internal_value(self, gf, data):
        return dateutil.parser.parse(data) if data is not None else None

    def clone(self):
        return Timestamp(self.name, parent=self.parent, derived=self.derived)


class Base64Field(Field):
    """\
    Timestamp field
    """
    def to_representation(self, value):
        return None if value is None else b64encode(value).decode('ascii')

    def to_internal_value(self, gf, data):
        return None if data is None else b64decode(data)

    def clone(self):
        return Base64Field(self.name, parent=self.parent, derived=self.derived)


class LinkedEntityCollection:
    """Represents a collection of linked entities, i.e. figures inside an analysis"""
    def __init__(self, entities, read_only=False, backlink_property=None, backlink=None):
        """\

        :param entities: list of entities
        :param read_only: if True, you won't be able to create new entities
        :param backlink_property: name of the property in each linked entity which will reference the parent object. \
        For example, if this collection stores figure revisions and backlink_property = "figure", you will \
        be able to refer to the parent figure as revision.figure.
        :param backlink: the parent object that backlink_property will point to
        """
        self._entities = list(entities)
        self.read_only = read_only
        self.backlink_property = backlink_property
        self.backlink = backlink

    def __iter__(self):
        return iter(self._entities)

    def __getitem__(self, item):
        return self._entities.__getitem__(item)

    def __repr__(self):
        return repr(self._entities)

    def __len__(self):
        return len(self._entities)

    def find(self, **kwargs):
        """\
        Returns the first object whose attributes match the query. E.g. find(name='hello', age=21) will return
        all objects where obj.name == "hello" and obj.age == 21.

        :param kwargs: query
        :return: first object that matches the query or None
        """
        for obj in self:
            if all(getattr(obj, name) == val for name, val in kwargs.items()):
                return obj

        return None

    def find_or_create(self, default_obj=None, **kwargs):
        """\
        Finds an object that matches query parameters. If the object doesn't exist, it will persist default_obj
        and return it instead.

        :param default_obj: object to create/persist if no matches are found
        :param kwargs: query parameters. See .find()
        :return: found or created object.

        """
        obj = self.find(**kwargs)
        if obj is not None:
            return obj
        elif default_obj is not None:
            self.create(default_obj)
            return default_obj
        else:
            raise RuntimeError(f"Could not find object: {kwargs}")

    def create(self, new_obj, **kwargs):
        """\
        Creates a new object and appends it to the collection.

        :param new_obj: object to create
        :return: created object

        """
        if self.read_only:
            raise RuntimeError("This collection is read only. Cannot create a new object.")

        if self.backlink_property is not None:
            setattr(new_obj, self.backlink_property, self.backlink)

        new_obj.create(**kwargs)
        self._entities.append(new_obj)
        return new_obj


class LinkedEntityField(Field):
    """\
    Represents a linked entity (or a collection of them), e.g. an Analysis inside a Workspace.
    """
    # pylint: disable=too-many-arguments
    def __init__(self, name, entity_type, many=False,
                 read_only=False, backlink_property=None, parent=None,
                 derived=False, sort_key=None, nested=False):
        """\

        :param name: field name
        :param entity_type: type of the linked entity, e.g. Analysis, Figure, etc.
        :param many: if False, will create a single linked entity. If True, will resolve to a LinkedEntityCollection
        :param read_only: Makes the collection of linked entities read-only. Only relevant if many=True.
        :param backlink_property: name of property in the linked entity which will point back to the parent
        :param parent: parent object
        :param derived: True if derived (won't be transmitted through the API)
        :param sort_key: sort key (callable) for entities. None if no sort (default).
        :param nested: True if this field is nested (i.e. it's embedded fully instead of linked by API ID)

        """
        super().__init__(name, parent=parent, derived=derived)
        self.entity_type = entity_type
        self.many = many
        self.read_only = read_only
        self.backlink_property = backlink_property
        self.sort_key = sort_key
        self.nested = nested

    def clone(self):
        return LinkedEntityField(self.name, self.entity_type,
                                 many=self.many, read_only=self.read_only,
                                 backlink_property=self.backlink_property,
                                 parent=self.parent, derived=self.derived,
                                 sort_key=self.sort_key, nested=self.nested)

    def to_representation(self, value):
        def _get_api_id(obj):
            if self.nested:
                return obj.to_json()

            if isinstance(obj, str):
                return obj
            else:
                return obj.api_id

        if value is None:
            return None
        elif self.many:
            sorted_value = value if self.sort_key is None else sorted(value, key=self.sort_key)
            return [_get_api_id(x) for x in sorted_value]
        else:
            return _get_api_id(value)

    def to_internal_value(self, gf, data):
        make_prefetched = lambda obj: self.entity_type(gf)(parse=True, **obj)
        make_not_prefetched = lambda api_id: self.entity_type(gf)(api_id=api_id)
        make_one = lambda obj: make_not_prefetched(obj) if isinstance(obj, str) else make_prefetched(obj)

        if data is None:
            return None
        elif self.many:
            sorted_vals = [make_one(api_id) for api_id in data]
            if self.sort_key is not None:
                sorted_vals = sorted(sorted_vals, key=self.sort_key)
            return LinkedEntityCollection(sorted_vals,
                                          read_only=self.read_only,
                                          backlink_property=self.backlink_property,
                                          backlink=self.parent)
        else:
            return make_one(data)

class DataField(LinkedEntityField):
    """Customizes a LinkedEntityField so that the entity data is fully embedded in the representation"""
    def clone(self):
        return DataField(self.name, self.entity_type,
                         many=self.many, read_only=self.read_only,
                         backlink_property=self.backlink_property,
                         parent=self.parent, derived=self.derived,
                         sort_key=self.sort_key)

    def _assert_not_shallow(self, obj):
        if obj.api_id is not None and obj.data is None:  # pylint: disable=protected-access
            raise ValueError("This is a shallow Data object without any data. It cannot be saved. "
                             "Please call fetch() first.")

        return True

    def to_representation(self, value):
        if value is None:
            return None
        elif self.many:
            sorted_value = value if self.sort_key is None else sorted(value, key=self.sort_key)
            return [x.to_json() for x in sorted_value if self._assert_not_shallow(x)]
        else:
            self._assert_not_shallow(value)
            return value.to_json()


class NestedMixin(abc.ABC):
    """\
    Nested objects: these are not standalone (cannot be manipulated based on API ID), but are directly embedded
    inside other objects.
    """
    def to_json(self):
        """Converts this object to JSON"""
        raise NotImplementedError

    @classmethod
    def from_json(cls, data):
        """Parses this object from JSON"""
        raise NotImplementedError

    def __eq__(self, other):
        return self.to_json() == other.to_json()


class ModelMixin(abc.ABC):
    """Base class for GoFigr API entities: workspaces, analyses, figures, etc."""
    # pylint: disable=protected-access
    fields = ['api_id', "_shallow"]
    include_if_none = []
    endpoint = None
    _gf = None  # GoFigr instance. Will be set dynamically.

    def __init__(self, api_id=None, parse=False, **kwargs):
        """

        :param api_id: API ID
        :param parse: if True, the fields' to_internal_value will be called on all properties. Otherwise, properties \
        will be stored verbatim. This is to support direct object creation from Python (i.e. parse = False), and \
        creation from JSON primitives (i.e. parse = True).
        :param kwargs:

        """
        self.api_id = api_id
        fields = [Field(x) if isinstance(x, str) else x.clone()
                  for x in self.fields]
        for fld in fields:
            fld.parent = self
        self.fields = {fld.name: fld for fld in fields}

        # Set all fields to None by default
        for name in self.fields:
            if not hasattr(self, name):
                setattr(self, name, None)

        self._update_properties(kwargs, parse=parse)

    def __eq__(self, other):
        repr1 = self.to_json()
        repr2 = other.to_json()

        if not set(repr1.keys()) == set(repr2.keys()):
            return False
        else:
            return all(repr1[k] == repr2[k] for k in repr1.keys()
                       if not isinstance(self.fields[k], Timestamp))

    def __hash__(self):
        raise RuntimeError("Model instances are not hashable")

    @property
    def app_url(self):
        """Gets the URL to this object in the GoFigr web app"""
        return os.path.join(self._gf.app_url, self.endpoint, self.api_id)

    @classmethod
    def from_json(cls, data):
        """Parses an instance of this class from JSON data"""
        return cls(**data, parse=True)

    def to_json(self, include_derived=True, include_none=False):
        """\
        Serializes this model to JSON primitives.

        :param include_derived: if True, derived fields will be included in the representation
        :param include_none: if True, fields set to None will be included in the representation
        :return: this object (and all nested/referenced fields) serialized to JSON primitives.
        """
        data = {fld.name: fld.to_representation(getattr(self, fld.name, None))
                for fld in self.fields.values()
                if (not fld.derived or include_derived)}
        if not include_none:
            data = {k: v for k, v in data.items() if (v is not None) or (k in self.include_if_none)}

        return data

    def _update_properties(self, props, parse=True):
        for name, val in props.items():
            if name not in self.fields:
                continue

            field = self.fields[name]
            setattr(self, name, field.to_internal_value(self._gf, val) if parse else val)

        return self

    @property
    def client(self):
        """Returns the underlying GoFigr instance"""
        return self._gf

    @classmethod
    def list(cls):
        """\
        Lists all objects from the server.

        """
        res = cls._gf._get(cls.endpoint)
        return [cls(**obj, parse=True) for obj in res.json()]

    def save(self, create=False, patch=False, silent=False):
        """\
        Saves this object to server

        :param create: will create the object if it doesn't already exist. Otherwise, saving a non-existing object \
        will throw an exception.
        :param patch: if True, will submit a partial update where some required properties may be missing. \
        You will almost never use this: it's only useful if for some reason you can't/don't want to fetch the full \
        object before updating properties. However, the web app relies on this functionality so it's available.
        :param silent: if True, the server will not generate an activity for this update.
        :return: self
        """
        if self.api_id is None:
            if create:
                return self.create(update=False)
            else:
                raise RuntimeError("API ID is None. Did you forget to create() the object first?")

        if silent:
            params = "?silent=true"
        else:
            params = ""

        method = self._gf._patch if patch else self._gf._put
        with MeasureExecution("Save request"):
            response = method(urljoin(self.endpoint, self.api_id) + "/" + params,
                              json=self.to_json(include_derived=False),
                              expected_status=HTTPStatus.OK)

        with MeasureExecution("Parse response"):
            self._update_properties(response.json())
        return self

    def _check_api_id(self):
        if self.api_id is None:
            raise RuntimeError("API ID is None")

    def fetch(self):
        """\
        Updates all fields from the server. Note that any unsaved local changes will be overwritten.

        :return: self
        """
        self._check_api_id()
        obj = self._gf._get(urljoin(self.endpoint, self.api_id + "/")).json()
        return self._update_properties(obj)

    def create(self, update=False):
        """\
        Creates this object on the server.

        :param update: if True and the object already exists, its properties will be updated on the server. Otherwise
        trying to create an object which already exists will throw an exception.

        :return: self
        """
        if self.api_id is not None:
            if update:
                return self.save()
            else:
                raise RuntimeError("This entity already exists. Cannot create.")

        response = self._gf._post(self.endpoint, json=self.to_json(include_derived=False),
                                  expected_status=HTTPStatus.CREATED)
        self._update_properties(response.json())
        return self

    def delete(self, **kwargs):
        """\
        Deletes an object on the server. This cannot be undone.

        :param kwargs: specify delete=True to actually delete the object.
        :return:

        """
        self._check_api_id()

        if 'delete' not in kwargs or not kwargs['delete']:
            raise RuntimeError("Specify delete=True to delete this object. This cannot be undone.")

        return self._gf._delete(urljoin(self.endpoint, self.api_id + "/"))

    def __repr__(self):
        str_val = str(self.to_json())
        if len(str_val) > 2048:
            return f"{str_val[:2045]}..."
        else:
            return str_val


class LinkSharingStatus(NestedMixin):
    """Stores the status of link sharing for shareable objects."""
    def __init__(self, enabled):
        self.enabled = enabled

    @classmethod
    def from_json(cls, data):
        return LinkSharingStatus(enabled=data.get('enabled', False))

    def to_json(self):
        return {'enabled': self.enabled}

    def __repr__(self):
        return str(self.to_json())


class SharingUserData(NestedMixin):
    """Stores information about a user that an object has been shared with"""
    def __init__(self, username, sharing_enabled):
        if username is None:
            raise ValueError("Username cannot be None.")
        elif sharing_enabled is None:
            raise ValueError("sharing_enabled cannot be None")

        self.username = username
        self.sharing_enabled = sharing_enabled

    @classmethod
    def from_json(cls, data):
        return SharingUserData(username=data.get('username'),
                               sharing_enabled=data.get('sharing_enabled'))

    def to_json(self):
        return {'username': self.username,
                'sharing_enabled': self.sharing_enabled}

    def __repr__(self):
        return str(self.to_json())


class MembershipInfo(NestedMixin):
    """Stores information about a member of a workspace"""
    def __init__(self, username, membership_type):
        if username is None:
            raise ValueError("Username cannot be None")

        self.username = username
        self.membership_type = membership_type

    @classmethod
    def from_json(cls, data):
        return MembershipInfo(username=data.get('username'),
                              membership_type=data.get('membership_type'))

    def to_json(self):
        return {'username': self.username,
                'membership_type': self.membership_type}

    def __repr__(self):
        return str(self.to_json())


class FlexibleStorageInfo(NestedMixin):
    """Stores information required for flexible storage"""
    def __init__(self, vendor, params):
        self.vendor = vendor
        self.params = params

    @classmethod
    def from_json(cls, data):
        return FlexibleStorageInfo(vendor=data.get('vendor'),
                                   params=data.get('params'))

    def to_json(self):
        return {'vendor': self.vendor,
                'params': self.params}

    def __repr__(self):
        return str(self.to_json())



class LogItem(NestedMixin):
    # pylint: disable=too-many-instance-attributes, too-many-arguments

    """\
    Represents an activity item, such as a figure being created or modified.

    """
    def __init__(self, username, timestamp, action, target_id, target_type,
                 deleted_sentinel=None,
                 deleted=False,
                 thumbnail=None,
                 target_name=None,
                 analysis_id=None,
                 analysis_name=None,
                 api_id=None,
                 gf=None,
                 parent=None):
        """\

        :param username: user who performed the activity
        :param timestamp: time the activity was performed
        :param action: Type of action (a string): create, create_child, view, update, move, delete
        :param target_id: API ID of the target object
        :param target_type: type of the target object
        :param deleted_sentinel: if this is a delete action (target no longer exists), this field captures the name of
        the entity that was deleted
        :param deleted: True if target was deleted
        :param thumbnail: base-64 encoded thumbnail image of the target object
        :param target_name: not used
        :param analysis_id: ID of the parent analysis
        :param analysis_name: name of the parent analysis
        :param api_id: API ID for this activity
        :param gf: GoFigr client instance
        :param parent: parent object, e.g. Workspace or Analysis
        """
        self.username, self.timestamp, self.action = username, timestamp, action
        self.target_id, self.target_type = target_id, target_type
        self.deleted, self.deleted_sentinel = deleted, deleted_sentinel
        self.thumbnail = thumbnail
        self.target_name = target_name
        self.analysis_id = analysis_id
        self.analysis_name = analysis_name
        self.api_id = api_id
        self.gf = gf
        self.parent = parent

    def fetch(self):
        """Fetches information about this log item from the server. API ID and parent have to be set."""
        if self.api_id is None:
            raise ValueError("API ID is None")
        elif self.parent is None:
            raise ValueError("Parent is None")
        elif self.parent.api_id is None:
            raise ValueError("Parent API ID is None")

        # pylint: disable=protected-access
        obj = self.gf._get(urljoin(self.parent.endpoint + "/" + self.parent.api_id + "/log/", self.api_id + "/")).json()

        if 'timestamp' in obj.keys():
            obj['timestamp'] = dateutil.parser.parse(obj['timestamp'])

        for name, value in obj.items():
            setattr(self, name, value)

        return self

    @classmethod
    def from_json(cls, data, gf=None, parent=None):
        timestamp = data.get('timestamp')
        if timestamp:
            timestamp = dateutil.parser.parse(timestamp)

        return LogItem(username=data.get('username'),
                       timestamp=timestamp,
                       action=data.get('action'),
                       target_id=data.get('target_id'),
                       target_type=data.get('target_type'),
                       target_name=data.get('target_name'),
                       deleted_sentinel=data.get('deleted_sentinel'),
                       deleted=data.get('deleted'),
                       thumbnail=data.get('thumbnail'),
                       analysis_id=data.get('analysis_id'),
                       analysis_name=data.get('analysis_name'),
                       api_id=data.get('api_id'),
                       gf=gf,
                       parent=parent)

    def to_json(self):
        return {'username': self.username,
                'timestamp': self.timestamp,
                'action': self.action,
                'target_id': self.target_id,
                'target_type': self.target_type,
                'target_name': self.target_name,
                'deleted_sentinel': self.deleted_sentinel,
                'thumbnail': self.thumbnail,
                'deleted': self.deleted,
                'analysis_id': self.analysis_id,
                'analysis_name': self.analysis_name,
                'api_id': self.api_id}

    def __repr__(self):
        return str(self.to_json())


class ShareableModelMixin(ModelMixin):
    """\
    Mixins for things we can share: analyses, figures, revisions, etc.

    """
    # pylint: disable=protected-access

    def set_link_sharing(self, enabled):
        """\
        Enabled or disables link sharing.

        :param enabled: true to enable, false to disable.
        :return: confirmation of link sharing status (true or false)
        """
        response = self._gf._post(urljoin(self.endpoint, f'{self.api_id}/share/link/'),
                                  json=LinkSharingStatus(enabled=enabled).to_json(),
                                  expected_status=HTTPStatus.OK)
        return LinkSharingStatus(response.json()).enabled

    def get_link_sharing(self):
        """\
        Gets current status of link sharing

        :return: true if link sharing is enabled, false otherwise.
        """
        response = self._gf._get(urljoin(self.endpoint, f'{self.api_id}/share/link/'),
                                 expected_status=HTTPStatus.OK)
        return LinkSharingStatus.from_json(response.json()).enabled

    def share(self, username):
        """\
        Shares this object with a specific user.

        :param username: name of the user to share with.
        :return: SharingUserData object

        """
        response = self._gf._post(urljoin(self.endpoint, f'{self.api_id}/share/user/'),
                                  json=SharingUserData(username=username, sharing_enabled=True).to_json(),
                                  expected_status=HTTPStatus.OK)
        return SharingUserData.from_json(response.json())

    def unshare(self, username):
        """\
        Unshares this object from a user.

        :param username: username of a user from whom to remove access
        :return: SharingUserData

        """
        response = self._gf._post(urljoin(self.endpoint, f'{self.api_id}/share/user/'),
                                  json=SharingUserData(username=username, sharing_enabled=False).to_json(),
                                  expected_status=HTTPStatus.OK)
        return SharingUserData.from_json(response.json())

    def get_sharing_users(self):
        """\
        Gets a list of all users with whom this object has been shared.

        :return: list of SharingUserData objects.

        """
        response = self._gf._get(urljoin(self.endpoint, f'{self.api_id}/share/user/'),
                                 expected_status=HTTPStatus.OK)
        return [SharingUserData.from_json(datum) for datum in response.json()]


TIMESTAMP_FIELDS = ["created_by", Timestamp("created_on"),
                    "updated_by", Timestamp("updated_on")]

CHILD_TIMESTAMP_FIELDS = ["child_updated_by", Timestamp("child_updated_on")]


class WorkspaceType(abc.ABC):
    """Enum for workspace type"""
    SECONDARY = "secondary"
    PRIMARY = "primary"


class WorkspaceMembership(abc.ABC):
    """Enum for levels of workspace membership: owner, viewer, etc."""
    OWNER = "owner"
    ADMIN = "admin"
    CREATOR = "creator"
    VIEWER = "viewer"

    ALL_LEVELS = [OWNER, ADMIN, CREATOR, VIEWER]


class OrganizationMembership(abc.ABC):
    """Enum for organizational membership"""
    ORG_ADMIN = "org_admin"
    WORKSPACE_ADMIN = "workspace_admin"
    WORKSPACE_CREATOR = "workspace_creator"
    WORKSPACE_VIEWER = "workspace_viewer"

    ALL_LEVELS = [ORG_ADMIN, WORKSPACE_ADMIN, WORKSPACE_CREATOR, WORKSPACE_VIEWER]



Recents = namedtuple("Recents", ["analyses", "figures", "assets"])


class LogsMixin:
    """\
    Mixin for entities which support the /log/ endpoint.

    """
    def get_logs(self):
        """\
        Retrieves the activity log.

        :return: list of LogItem objects.
        """
        # pylint: disable=protected-access
        response = self._gf._get(urljoin(self.endpoint, f'{self.api_id}/log/'),
                                 expected_status=HTTPStatus.OK)
        return [LogItem.from_json(datum, gf=self._gf, parent=self) for datum in response.json()]


class ThumbnailMixin:
    """\
    Mixin for entities which support the /log/ endpoint.

    """
    def get_thumbnail(self, size):
        """\
        Retrieves the thumbnail image.
        :param size: size in pixels

        :return: PIL.Image if available or None
        """
        # pylint: disable=protected-access
        response = self._gf._get(urljoin(self.endpoint, f'{self.api_id}/thumbnail/{size}'),
                                 expected_status=HTTPStatus.OK)

        data = response.json()
        thumb_b64 = data.get('thumbnail')

        if not thumb_b64:
            return None

        img_data = b64decode(thumb_b64)
        bio = io.BytesIO(img_data)
        img = PIL.Image.open(bio)
        img.load()
        return img


class MembersMixin:
    """Mixin for entities which support the /members/ endpoint."""

    def get_members(self, unauthorized_error=True):
        """\
        Gets members of this workspace.

        :param unauthorized_error: whether to raise an exception if unauthorized

        :return: list of WorkspaceMember objects
        """
        try:
            response = self._gf._get(urljoin(self.endpoint, f'{self.api_id}/members/'),
                                     expected_status=HTTPStatus.OK)
            return [MembershipInfo.from_json(datum) for datum in response.json()]
        except UnauthorizedError:
            if unauthorized_error:
                raise
            else:
                return []

    def add_member(self, username, membership_type):
        """\
        Adds a member to this workspace.

        :param username: username of the person to add
        :param membership_type: WorkspaceMembership value, e.g. WorkspaceMembership.CREATOR
        :return: WorkspaceMember instance
        """
        response = self._gf._post(urljoin(self.endpoint, f'{self.api_id}/members/add/'),
                                  json=MembershipInfo(username=username, membership_type=membership_type).to_json(),
                                  expected_status=HTTPStatus.OK)

        return MembershipInfo.from_json(response.json())

    def change_membership(self, username, membership_type):
        """\
        Changes the membership level for a user.

        :param username: username
        :param membership_type: new membership type, e.g. WorkspaceMembership.CREATOR
        :return: WorkspaceMember instance

        """
        response = self._gf._post(urljoin(self.endpoint, f'{self.api_id}/members/change/'),
                                  json=MembershipInfo(username=username, membership_type=membership_type).to_json(),
                                  expected_status=HTTPStatus.OK)

        return MembershipInfo.from_json(response.json())

    def remove_member(self, username):
        """\
        Removes a member from this workspace.

        :param username: username
        :return: WorkspaceMember instance

        """
        response = self._gf._post(urljoin(self.endpoint, f'{self.api_id}/members/remove/'),
                                  json=MembershipInfo(username=username, membership_type=None).to_json(),
                                  expected_status=HTTPStatus.OK)

        return MembershipInfo.from_json(response.json())


class FlexibleStorageMixin:
    """Mixin for getting/setting custom storage parameters if allowed by subscription"""
    def get_storage_info(self):
        """\
        Gets the storage information for this workspace/organization.

        :return: FlexibleStorateInfo instance
        """
        response = self._gf._get(urljoin(self.endpoint, f'{self.api_id}/storage/'),
                                 expected_status=HTTPStatus.OK)
        return FlexibleStorageInfo.from_json(response.json())

    def set_storage_info(self, vendor, params):
        """\
        Sets the storage information for this workspace/organization.

        :param vendor: vendor name
        :param params: vendor-specific storage parameters
        :return: FlexibleStorageInfo instance returned from the server

        """
        response = self._gf._post(urljoin(self.endpoint, f'{self.api_id}/storage/'),
                                  json=FlexibleStorageInfo(vendor, params).to_json(),
                                  expected_status=HTTPStatus.OK)
        return FlexibleStorageInfo.from_json(response.json())

    def test_storage(self, vendor, params):
        """\
        Runs a storage test for flexible storage parameters.

        :param vendor: vendor name
        :param params: vendor-specific storage parameters
        :return: FlexibleStorageInfo instance returned from the server

        """
        response = self._gf._post(urljoin(self.endpoint, f'{self.api_id}/storage/test/'),
                                  json=FlexibleStorageInfo(vendor, params).to_json(),
                                  expected_status=HTTPStatus.OK)
        return FlexibleStorageInfo.from_json(response.json())


class gf_Organization(ModelMixin, LogsMixin, MembersMixin, FlexibleStorageMixin):
    """Represents a workspace"""
    # pylint: disable=protected-access

    fields = ["api_id",
              "name",
              "email",
              "description",
              "allow_per_workspace_storage_settings",
              LinkedEntityField("workspaces", lambda gf: gf.Workspace, many=True, derived=True,
                                backlink_property='organization')]
    endpoint = "organization/"

    def get_invitations(self):
        """\
        Gets members of this workspace.

        :return: list of WorkspaceMember objects
        """
        response = self._gf._get(urljoin(self.endpoint, f'{self.api_id}/invitations/'),
                                 expected_status=HTTPStatus.OK)
        return [self._gf.OrganizationInvitation(**datum, parse=True) for datum in response.json()]


class gf_Workspace(ModelMixin, LogsMixin, MembersMixin, FlexibleStorageMixin):
    """Represents a workspace"""
    # pylint: disable=protected-access

    fields = ["api_id",
              "_shallow",
              "name",
              "description",
              "workspace_type",
              "size_bytes",
              LinkedEntityField("organization", lambda gf: gf.Organization, many=False),
              LinkedEntityField("analyses", lambda gf: gf.Analysis, many=True, derived=True,
                                backlink_property='workspace'),
              LinkedEntityField("assets", lambda gf: gf.Asset, many=True, derived=True,
                                backlink_property='workspace')
              ] + TIMESTAMP_FIELDS + CHILD_TIMESTAMP_FIELDS
    include_if_none = ["organization"]
    endpoint = "workspace/"

    def get_analysis(self, name, create=True, **kwargs):
        """\
        Finds an analysis by name.

        :param name: name of the analysis
        :param create: whether to create an analysis if one doesn't exist
        :param kwargs: if an Analysis needs to be created, parameters of the Analysis object (such as description)
        :return: Analysis instance.
        """
        if self.analyses is None:
            self.fetch()

        return self.analyses.find_or_create(name=name,
                                            default_obj=self._gf.Analysis(name=name, **kwargs) if create else None)

    def get_invitations(self):
        """\
        Gets members of this workspace.

        :return: list of WorkspaceMember objects
        """
        response = self._gf._get(urljoin(self.endpoint, f'{self.api_id}/invitations/'),
                                 expected_status=HTTPStatus.OK)
        return [self._gf.WorkspaceInvitation(**datum, parse=True) for datum in response.json()]


    def get_recents(self, limit=100):
        """\
        Gets the most recently created or modified analyses & figures.

        :param limit: maximum number of elements to retrieve.
        :return: Instance of the Recents object
        """
        response = self._gf._get(urljoin(self.endpoint, f'{self.api_id}/recent/?limit={limit}'),
                                         expected_status=HTTPStatus.OK)
        data = response.json()
        analyses = [self._gf.Analysis(**datum) for datum in data.get("analyses", [])]
        figures = [self._gf.Figure(**datum) for datum in data.get("figures", [])]
        assets = [self._gf.Asset(**datum) for datum in data.get("assets", [])]
        return Recents(analyses, figures, assets)


class gf_Analysis(ShareableModelMixin, LogsMixin, ThumbnailMixin):
    """Represents an analysis"""
    # pylint: disable=protected-access

    fields = ["api_id",
              "_shallow",
              "name",
              "description",
              "size_bytes",
              LinkedEntityField("workspace", lambda gf: gf.Workspace, many=False),
              LinkedEntityField("figures", lambda gf: gf.Figure, many=True, derived=True,
                                backlink_property='analysis')] + TIMESTAMP_FIELDS + CHILD_TIMESTAMP_FIELDS
    endpoint = "analysis/"

    def get_figure(self, name, create=True, **kwargs):
        """\
        Finds a figure by name, optionally creating it.

        :param name: name of the figure to find
        :param create: True to create the figure if it doesn't exist.
        :param kwargs: parameters to Figure (e.g. description) if it needs to be created
        :return: Figure instance

        """
        if self.figures is None:
            self.fetch()

        return self.figures.find_or_create(name=name,
                                           default_obj=self._gf.Figure(name=name, **kwargs) if create else None)


class gf_Figure(ShareableModelMixin, ThumbnailMixin):
    """Represents a figure"""
    fields = ["api_id",
              "_shallow",
              "name",
              "description",
              "size_bytes",
              LinkedEntityField("analysis", lambda gf: gf.Analysis, many=False),
              LinkedEntityField("revisions", lambda gf: gf.Revision, many=True,
                                derived=True, backlink_property='figure')
              ] + TIMESTAMP_FIELDS + CHILD_TIMESTAMP_FIELDS
    endpoint = "figure/"


class gf_Asset(ShareableModelMixin, ThumbnailMixin):
    """Represents an asset, e.g. a file or a dataset"""
    fields = ["api_id",
              "name",
              "description",
              "size_bytes",
              LinkedEntityField("workspace", lambda gf: gf.Workspace, many=False),
              LinkedEntityField("revisions", lambda gf: gf.AssetRevision, many=True,
                                derived=True, backlink_property='asset')
              ] + TIMESTAMP_FIELDS + CHILD_TIMESTAMP_FIELDS
    endpoint = "asset/"

    @classmethod
    def find_by_name(cls, name):
        """\
        Finds an asset by name.

        :param name: name to search for
        :return: Asset instances, or empty list if not found

        """
        if name is None:
            raise ValueError("Name cannot be None")

        response = cls._gf._post(urljoin(cls.endpoint, 'find_by_name/'),
                                json={'name': name},
                                expected_status=HTTPStatus.OK)
        return [cls.from_json(datum) for datum in response.json()]


class DataType(abc.ABC):
    """\
    Enum for different types of data we can store inside a FigureRevision.
    """
    DATA_FRAME = "dataframe"
    CODE = "code"
    IMAGE = "image"
    TEXT = "text"
    FILE = "file"


class MetadataProxyField:
    """Field which is embedded inside the JSON metadata"""
    def __init__(self, name, default=None):
        """

        :param name: name of the field
        :param default: default value
        """
        self.name = name
        self.default = default

    def __get__(self, instance, owner):
        """\
        Retrieves the field value.

        :param instance:
        :param owner:
        :return:
        """
        return instance.metadata.get(self.name, self.default)

    def __set__(self, instance, value):
        """\
        Sets the field value.

        :param instance:
        :param value:
        :return:
        """
        if not hasattr(instance, 'metadata') or instance.metadata is None:
            instance.metadata = {}

        instance.metadata[self.name] = value

    def __delete__(self, instance):
        """\
        Deletes the field.

        :param instance:
        :return:
        """
        if instance.metadata is None:
            return
        elif self.name in instance.metadata:
            del instance.metadata[self.name]


class gf_Data(ModelMixin):
    """Represents binary data (e.g. image data, serialized dataframes, etc.)"""
    # pylint: disable=no-member

    SPECIALIZED_TYPES = None
    DATA_TYPE = None

    fields = ["api_id",
              "name",
              "type",
              "hash",
              "size_bytes",
              JSONField("metadata"),
              Base64Field("data")]

    metadata_fields = []

    endpoint = "data/"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.type = kwargs.pop('type', self.DATA_TYPE)
        self.metadata = kwargs.pop('metadata', {})

        # Assign metadata fields
        for meta in self.metadata_fields:
            if meta.name in kwargs:
                self.metadata[meta.name] = kwargs[meta.name]
            elif meta.name not in self.metadata:
                self.metadata[meta.name] = meta.default

        # Assign a new local ID (unless one already exists)
        if 'local_id' in kwargs:
            self.local_id = kwargs['local_id']

        if self.local_id is None:
            self.local_id = str(uuid4())

    def calculate_hash(self, hash_type="blake3"):
        """\
        Calculates the hash of the instance's data.

        :param hash_type: The type of hash algorithm to use. Defaults to "blake3".
                          Currently, only "blake3" is supported.
        :type hash_type: str, optional
        :return: The hexadecimal representation of the hash if data exists, otherwise None.
        :rtype: str or None
        :raises ValueError: If an unsupported hash_type is specified.
        """
        if not self.data:
            return None
        if hash_type == "blake3":
            return blake3(self.data).hexdigest()  # pylint: disable=not-callable
        else:
            raise ValueError(f"Unsupported hash type: {hash_type}")

    @property
    def local_id(self):
        """Reserved for internal API use"""
        if self.metadata is None or 'local_id' not in self.metadata:
            return None

        return self.metadata['local_id']

    @local_id.setter
    def local_id(self, value):
        """Reserved for internal API use"""
        if self.metadata is None:
            self.metadata = {}

        self.metadata['local_id'] = value

    @property
    def is_shallow(self):
        """True if this is a shallow data object without the byte payload"""
        return self.api_id is not None and self.data is None

    def specialize(self):
        """Creates a specialized data instance, e.g. ImageData, based on the data type"""
        supported_types = {
            DataType.IMAGE: self.client.ImageData,
            DataType.CODE: self.client.CodeData,
            DataType.TEXT: self.client.TextData,
            DataType.DATA_FRAME: self.client.TableData,
            DataType.FILE: self.client.FileData
        }
        if self.type not in supported_types:
            raise ValueError(f"Unsupported data type: {self.type}. No specialized class exists.")

        return supported_types[self.type](api_id=self.api_id,
                                          name=self.name,
                                          type=self.type,
                                          metadata=self.metadata,
                                          data=self.data,
                                          size_bytes=self.size_bytes)

    def get_storage_info(self):
        """\
        Gets the storage information for this workspace/organization.

        :return: FlexibleStorateInfo instance
        """
        response = self._gf._get(urljoin(self.endpoint, f'{self.api_id}/storage/'),
                                 expected_status=HTTPStatus.OK)
        return response.json()

    def __eq__(self, other):
        repr1 = self.to_json()
        repr2 = other.to_json()

        if not set(repr1.keys()) == set(repr2.keys()):
            return False
        else:
            return all(repr1[k] == repr2[k] for k in repr1.keys()
                       if not isinstance(self.fields[k], Timestamp) and k != "api_id")

    def __repr__(self):
        dat = self.to_json()
        dat['data'] = f"<{len(self.data)} bytes>" if self.data else None
        return str(dat)


class gf_ImageData(gf_Data):
    """Binary image data"""
    # pylint: disable=no-member

    DATA_TYPE = DataType.IMAGE

    is_watermarked = MetadataProxyField("is_watermarked", default=False)
    format = MetadataProxyField("format")
    metadata_fields = [is_watermarked, format]

    @property
    def is_interactive(self):
        """True if this figure is interactive, false otherwise"""
        return self.format == "html"

    @property
    def image(self):
        """\
        Returns this image as a PIL.Image object.

        :return: PIL.Image
        """
        if self.is_interactive:
            raise RuntimeError("This is an interactive figure.")

        if self.data is None:
            return None

        bio = io.BytesIO(self.data)
        img = PIL.Image.open(bio)
        img.load()
        return img


class gf_FileData(gf_Data):
    """Binary file data"""
    # pylint: disable=no-member

    DATA_TYPE = DataType.FILE

    path = MetadataProxyField("path")
    metadata_fields = [path]

    @classmethod
    def read(cls, path):
        """\
        Creates a new FileData object from the contents of a file.

        :param path: path of the file to read
        :return: FileData object
        """
        with open(path, 'rb') as f:
            return cls(data=f.read(), name=os.path.basename(path), path=path)

    def write(self, path):
        """Writes the contents of this file to the given path"""
        with open(path, 'wb') as f:
            f.write(self.data)


class CodeLanguage(abc.ABC):
    """\
    For code data objects, the programming language of the embedded code.
    """
    PYTHON = "Python"
    R = "R"


class gf_CodeData(gf_Data):
    """Serialized code data (it's text, but stored and transmitted as bytes)"""
    # pylint: disable=no-member

    DATA_TYPE = DataType.CODE

    language = MetadataProxyField("language")
    format = MetadataProxyField("format")
    encoding = MetadataProxyField("encoding", default="utf-8")
    metadata_fields = [language, format, encoding]

    def __init__(self, contents=None, **kwargs):
        """\

        :param contents: code string. Will be encoded and stored internally as bytes.
        :param kwargs: same parameters as the Data constructor
        """
        super().__init__(**kwargs)
        if contents is not None:
            self.contents = contents

        self.format = kwargs.get("format", "text")

    @property
    def contents(self):
        """\
        Code contents.

        :return:
        """
        return self.data.decode(self.encoding) if self.data is not None else None

    @contents.setter
    def contents(self, value):
        """\
        Sets the code contents.

        :param value:
        :return:
        """
        self.data = value.encode(self.encoding) if value is not None else None


class gf_TextData(gf_Data):
    """Serialized text data (even though it's text, we store and transmit bytes)"""
    # pylint: disable=no-member

    DATA_TYPE = DataType.TEXT
    encoding = MetadataProxyField("encoding", default="utf-8")
    metadata_fields = [encoding]

    def __init__(self, contents=None, **kwargs):
        super().__init__(**kwargs)
        if contents is not None:
            self.contents = contents

    @property
    def contents(self):
        """\
        Decoded text (a string)
        """
        return self.data.decode(self.encoding) if self.data is not None else None

    @contents.setter
    def contents(self, value):
        """\
        Setter for the text.

        :param value:
        :return:
        """
        self.data = value.encode(self.encoding) if value is not None else None


class gf_TableData(gf_Data):
    """Serialized data frame"""
    # pylint: disable=no-member

    DATA_TYPE = DataType.DATA_FRAME
    format = MetadataProxyField("format")
    encoding = MetadataProxyField("encoding", default="utf-8")
    metadata_fields = [format, encoding]

    def __init__(self, dataframe=None, **kwargs):
        """

        :param dataframe: pd.DataFrame to store. Will be converted to CSV and stored as bytes.
        :param kwargs: same as Data
        """
        super().__init__(**kwargs)
        self.format = "pandas/csv"

        if dataframe is not None:
            self.dataframe = dataframe

    @property
    def dataframe(self):
        """
        Parses the dataframe from the embedded stream of bytes.

        :return:
        """
        return pd.read_csv(io.BytesIO(self.data), encoding=self.encoding) if self.data is not None else None

    @dataframe.setter
    def dataframe(self, value):
        """\
        Stores the dataframe by converting to CSV and saving as bytes.

        :param value: pd.DataFrame instance
        :return:
        """
        self.data = value.to_csv().encode(self.encoding) if value is not None else None

class RevisionMixin(ShareableModelMixin):
    """Base class for revisions, e.g. FigureRevision or AssetRevision"""

    def _replace_data_type(self, data_type, value):
        """\
        Because different data types (image, text, etc.) are stored in a flat list, this is a convenience
        function to only replace data of a certain type and nothing else.

        :param data_type: type of data to replace
        :param value: value to replace it with
        :return: None

        """
        # pylint: disable=access-member-before-definition, attribute-defined-outside-init
        other = [dat for dat in self.data if dat.type != data_type]
        self.data = other + list(value)

    def _restore_data(self, data_copy):
        """\
        Restores data from a copy. This function is necessary because the API only returns shallow data objects
        (no bytes) which, based on the base ModelMixin, will overwrite actual data in this object.

        :param data_copy:
        :return:
        """
        # Fill in API IDs for data objects
        local_id_to_api_id = {obj.local_id: obj.api_id for obj in self.data}
        for datum in data_copy:
            datum.api_id = local_id_to_api_id[datum.local_id]

        self.data = data_copy  # pylint: disable=attribute-defined-outside-init
        return self

    def create(self, update=False):
        """\
        Creates a Revision on the server.

        :param update: True to update the object if it already exists
        :return: self

        """
        self._assert_data_not_shallow()

        # The server will return a shallow copy of the data objects, without the byte payload.
        # Instead of requesting that data separately (slow), we simply preserve the submitted data.
        data_copy = self.data
        super().create(update=update)

        self._restore_data(data_copy)
        return self

    def fetch(self, fetch_data=True):
        """\
        Overrides the default fetch to retrieve the data objects (with byte payload) as well. This override
        is necessary because the API only returns shallow data objects by default.

        :param fetch_data: whether to retrieve full data objects
        :return: self
        """
        super().fetch()
        if fetch_data:
            self.fetch_data()
        return self

    def save(self, create=False, patch=False, silent=False):
        self._assert_data_not_shallow()

        # The server will return a shallow copy of the data objects, without the byte payload.
        # Instead of requesting that data separately (slow), we simply preserve the submitted data.
        data_copy = self.data
        super().save(create=create, patch=patch, silent=silent)

        self._restore_data(data_copy)
        return self

    def _assert_data_not_shallow(self, message="This revision contains shallow data. Did you call fetch_data?"):
        for datum in self.data:
            if datum.is_shallow:
                raise RuntimeError(message)

    def fetch_data(self):
        """Fetches all data objects"""
        if self.data is None:
            return self

        for data in self.data:
            data.fetch()

        return self

    def _update_properties(self, props, parse=True):
        super()._update_properties(props, parse=parse)
        if self.data is None:
            self.data = []
        else:
            self.data = [dat.specialize() for dat in self.data]
        return self


class gf_AssetLinkedToFigure(ModelMixin):
    """Many-to-many relationship between figure and asset revisions"""

    fields = ["use_type",
              LinkedEntityField("figure_revision", lambda gf: gf.Revision, many=False),
              LinkedEntityField("asset_revision", lambda gf: gf.AssetRevision, many=False)]
    endpoint = None


class gf_Revision(RevisionMixin, ThumbnailMixin):
    """Represents a figure revision"""
    fields = ["api_id", "revision_index", "size_bytes",
              JSONField("metadata"),
              LinkedEntityField("figure", lambda gf: gf.Figure, many=False),
              LinkedEntityField("assets", lambda gf: gf.AssetLinkedToFigure, many=True, nested=True,
                                sort_key=lambda ds: ds.use_type),
              DataField("data", lambda gf: gf.Data, many=True),
              ] + TIMESTAMP_FIELDS

    endpoint = "revision/"

    def __init__(self, *args, **kwargs):
        self.backend = kwargs.pop('backend', None)

        super().__init__(*args, **kwargs)

    @property
    def revision_url(self):
        """Returns the GoFigr URL for this revision"""
        return f"{self._gf.app_url}/r/{self.api_id}"

    @property
    def image_data(self):
        """Returns only image data (if any)"""
        return [dat for dat in self.data if dat.type == DataType.IMAGE]

    @image_data.setter
    def image_data(self, value):
        self._replace_data_type(DataType.IMAGE, value)

    @property
    def file_data(self):
        """Returns only file data (if any)"""
        return [dat for dat in self.data if dat.type == DataType.FILE]

    @file_data.setter
    def file_data(self, value):
        self._replace_data_type(DataType.FILE, value)

    @property
    def table_data(self):
        """Returns only DataFrame data (if any)"""
        return [dat for dat in self.data if dat.type == DataType.DATA_FRAME]

    @table_data.setter
    def table_data(self, value):
        self._replace_data_type(DataType.DATA_FRAME, value)

    @property
    def code_data(self):
        """Returns only code data (if any)"""
        return [dat for dat in self.data if dat.type == DataType.CODE]

    @code_data.setter
    def code_data(self, value):
        self._replace_data_type(DataType.CODE, value)

    @property
    def text_data(self):
        """Returns only text data (if any)"""
        return [dat for dat in self.data if dat.type == DataType.TEXT]

    @text_data.setter
    def text_data(self, value):
        self._replace_data_type(DataType.TEXT, value)


class gf_AssetRevision(RevisionMixin, ThumbnailMixin):
    """Represents a figure revision"""
    fields = ["api_id", "revision_index", "size_bytes",
              JSONField("metadata"),
              LinkedEntityField("asset", lambda gf: gf.Asset, many=False),
              LinkedEntityField("figure_revisions", lambda gf: gf.AssetLinkedToFigure, many=True, nested=True,
                                sort_key=lambda ds: ds.use_type),
              DataField("data", lambda gf: gf.Data, many=True),
              ] + TIMESTAMP_FIELDS

    endpoint = "asset_revision/"

    @classmethod
    def find_by_hash(cls, digest, hash_type="blake3"):
        """\
        Finds an asset revision by its hash.

        :param digest: digest hash (text)
        :param hash_type: type of hash (only blake3 supported)
        :return: list of matching asset revisions, or empty list if not found

        """
        if digest is None:
            raise ValueError("Hash cannot be None")
        elif hash_type is None:
            raise ValueError("Hash type cannot be None")

        response = cls._gf._post(urljoin(cls.endpoint, 'find_by_hash/'),
                                 json={'digest': digest, 'hash_type': hash_type},
                                 expected_status=HTTPStatus.OK)
        return [cls.from_json(datum) for datum in response.json()]


class gf_ApiKey(ModelMixin):
    """\
    Represents an API key. The field 'token' is the actual token used to authenticate, and is always null
    except at key creation.

    """

    fields = ["api_id",
              "name",
              "token",
              Timestamp("created"),
              Timestamp("last_used"),
              Timestamp("expiry"),
              LinkedEntityField("workspace", lambda gf: gf.Workspace, many=False),]
    endpoint = "api_key/"

    def fetch_and_preserve_token(self):
        """\
        Like fetch(), but preserves the token if present. This is useful because the token is only available
        at creation, so calling fetch() will always set it to None.

        :return:
        """
        # pylint: disable=access-member-before-definition,attribute-defined-outside-init
        tok = self.token
        self.fetch()
        self.token = tok
        return self


class InvitationMixin(ModelMixin):
    """\
        Represents an invitation to join a workspace.

        """

    # pylint: disable=protected-access

    def _require_token(self):
        if self.token is None:
            raise ValueError("This action requires a valid token")

    def fetch(self):
        """\
        Updates all fields from the server. Note that any unsaved local changes will be overwritten.

        :return: self
        """
        if self.token is not None:
            obj = self._gf._get(urljoin(self.endpoint, self.token)).json()
        else:
            self._check_api_id()
            obj = self._gf._get(urljoin(self.endpoint, self.api_id)).json()

        return self._update_properties(obj)

    def delete(self, **kwargs):
        return self.client._delete(urljoin(self.endpoint, self.api_id))

    def accept(self):
        """Accepts this invitation"""
        self._require_token()
        return self.client._post(urljoin(self.endpoint, self.token + "/accept"), json={})

    fields = ["api_id",
              "email",
              "initiator",
              "token",
              "status",
              Timestamp("created"),
              Timestamp("expiry"),
              "membership_type"]


class gf_WorkspaceInvitation(InvitationMixin):
    """\
    Represents an invitation to join a workspace.

    """
    fields = InvitationMixin.fields + [LinkedEntityField("workspace", lambda gf: gf.Workspace, many=False)]
    endpoint = "invitations/workspace/"


class gf_OrganizationInvitation(InvitationMixin):
    """\
    Represents an invitation to join an organization.

    """
    fields = InvitationMixin.fields + [LinkedEntityField("organization", lambda gf: gf.Organization, many=False)]
    endpoint = "invitations/organization/"


class gf_MetadataProxy(ModelMixin):
    """\
    Represents a proxy object for sharing metadata between the GoFigr extension (server-side) and the Jupyter client.

    """
    # pylint: disable=protected-access
    def fetch(self):
        """\
        Updates all fields from the server. Note that any unsaved local changes will be overwritten.

        :return: self
        """
        obj = self._gf._get(urljoin(self.endpoint, self.token)).json()
        return self._update_properties(obj)

    def delete(self, **kwargs):
        return self.client._delete(urljoin(self.endpoint, self.token))

    def save(self, *args, **kwargs):  # pylint: disable=unused-argument
        response = self.client._post(urljoin(self.endpoint, self.token), json={'metadata': self.metadata})
        if response.json() is not None:
            self._update_properties(response.json())
        return self

    def update_metadata(self, metadata):
        """Accepts this invitation"""
        self._require_token()
        return self.client._post(urljoin(self.endpoint, self.token), json=metadata)

    fields = ["api_id",
              "initiator",
              "token",
              Timestamp("created"),
              Timestamp("expiry"),
              Timestamp("updated"),
              JSONField("metadata")]
    endpoint = "metadata/"

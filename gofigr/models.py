"""\
Copyright (c) 2022, Flagstaff Solutions, LLC
All rights reserved.

"""

import abc
import inspect
import io
from base64 import b64encode, b64decode
from collections import namedtuple
from http import HTTPStatus
from urllib.parse import urljoin

import PIL
import dateutil.parser

import pandas as pd


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

    def create(self, new_obj):
        """\
        Creates a new object and appends it to the collection.

        :param new_obj: object to create
        :return: created object

        """
        if self.read_only:
            raise RuntimeError("This collection is read only. Cannot create a new object.")

        if self.backlink_property is not None:
            setattr(new_obj, self.backlink_property, self.backlink)

        new_obj.create()
        self._entities.append(new_obj)
        return new_obj


class LinkedEntityField(Field):
    """\
    Represents a linked entity (or a collection of them), e.g. an Analysis inside a Workspace.
    """
    # pylint: disable=too-many-arguments
    def __init__(self, name, entity_type, lazy, many=False,
                 read_only=False, backlink_property=None, parent=None,
                 derived=False, sort_key=None, prefetched=False):
        """\

        :param name: field name
        :param entity_type: type of the linked entity, e.g. Analysis, Figure, etc.
        :param lazy: if True, the entity will only load once its properties are accessed or assigned to
        :param many: if False, will create a single linked entity. If True, will resolve to a LinkedEntityCollection
        :param read_only: Makes the collection of linked entities read-only. Only relevant if many=True.
        :param backlink_property: name of property in the linked entity which will point back to the parent
        :param parent: parent object
        :param derived: True if derived (won't be transmitted through the API)
        :param sort_key: sort key (callable) for entities. None if no sort (default).
        """
        super().__init__(name, parent=parent, derived=derived)
        self.entity_type = entity_type
        self.lazy = lazy
        self.many = many
        self.read_only = read_only
        self.backlink_property = backlink_property
        self.sort_key = sort_key
        self.prefetched = prefetched

    def clone(self):
        return LinkedEntityField(self.name, self.entity_type, self.lazy,
                                 many=self.many, read_only=self.read_only,
                                 backlink_property=self.backlink_property,
                                 parent=self.parent, derived=self.derived,
                                 sort_key=self.sort_key, prefetched=self.prefetched)

    def to_representation(self, value):
        if value is None:
            return None
        elif self.many:
            sorted_value = value if self.sort_key is None else sorted(value, key=self.sort_key)
            return [x.api_id for x in sorted_value]
        else:
            return value.api_id

    def to_internal_value(self, gf, data):
        if self.prefetched:
            make_one = lambda obj: self.entity_type(gf)(parse=True, **obj)
        else:
            make_one = lambda api_id: self.entity_type(gf)(api_id=api_id, lazy=self.lazy)

        if self.many:
            sorted_vals = [make_one(api_id) for api_id in data]
            if self.sort_key is not None:
                sorted_vals = sorted(sorted_vals, key=self.sort_key)
            return LinkedEntityCollection(sorted_vals,
                                          read_only=self.read_only,
                                          backlink_property=self.backlink_property,
                                          backlink=self.parent)
        else:
            return make_one(data)


class NestedEntityField(Field):
    """\
    Represents a nested entity. Nested entities are embedded fully in the parent object's JSON representation
    and cannot be manipulated on their own.
    """
    def __init__(self, name, entity_type, many=False, read_only=False, derived=False, parent=None):
        super().__init__(name, parent=parent, derived=derived)
        self.entity_type = entity_type
        self.many = many
        self.read_only = read_only

    def clone(self):
        return NestedEntityField(self.name, self.entity_type,
                                 many=self.many,
                                 read_only=self.read_only,
                                 derived=self.derived,
                                 parent=self.parent)

    def to_representation(self, value):
        if value is None:
            return None
        elif self.many:
            return [x.to_json() for x in value]
        else:
            return value.to_json()

    def to_internal_value(self, gf, data):
        make_one = lambda d: self.entity_type(gf).from_json(d)
        if self.many:
            coltype = tuple if self.read_only else list
            return coltype([make_one(d) for d in data])
        else:
            return make_one(data)


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


class ModelMixin(abc.ABC):
    """Base class for GoFigr API entities: workspaces, analyses, figures, etc."""
    # pylint: disable=protected-access
    fields = ['api_id', ]
    endpoint = None
    _gf = None  # GoFigr instance. Will be set dynamically.

    def __init__(self, api_id=None, lazy=False, parse=False, **kwargs):
        """

        :param api_id: API ID
        :param lazy: if True, parameters won't be fetched from server until needed. Otherwise they will \
        be fetched right away.
        :param parse: if True, the fields' to_internal_value will be called on all properties. Otherwise, properties \
        will be stored verbatim. This is to support direct object creation from Python (i.e. parse = False), and \
        creation from JSON primitives (i.e. parse = True).
        :param kwargs:

        """
        if lazy and len(kwargs) > 0:
            raise ValueError("Parameter values for lazy instances will be fetched on first use and "
                             "cannot be supplied in the constructor")

        self.api_id = api_id
        self.lazy = lazy
        self._has_data = not lazy
        fields = [Field(x) if isinstance(x, str) else x.clone()
                  for x in self.fields]
        for fld in fields:
            fld.parent = self
        self.fields = {fld.name: fld for fld in fields}

        # Set all fields to None by default
        for name in self.fields:
            if not lazy and not hasattr(self, name):
                setattr(self, name, None)

        self._update_properties(kwargs, parse=parse)

    def __getattr__(self, item):
        # Note that this function is only called if the attribute isn't found through
        # the usual means
        err = AttributeError(f"No such attribute: {item}")
        if item not in self.fields:
            raise err
        elif not self.lazy:
            raise err
        else:  # lazy AND item in self.fields
            if self._has_data:  # already fetched and no dice
                raise err

            self.fetch()
            return getattr(self, item)

    def __setattr__(self, key, value):
        try:
            # We may be setting attributes in the constructor where these properties
            # only partially exist. In that case, we want to avoid infinite recursion
            # (hence call to getter from super). We also want to avoid fetching any data if
            # these key attributes are still missing (hence try-except).
            lazy_fields = super().__getattribute__('fields')
            is_lazy = super().__getattribute__('lazy')
            has_data = super().__getattribute__('_has_data')

            do_fetch = key != 'api_id' and key in lazy_fields and is_lazy and not has_data
        except AttributeError:
            do_fetch = False

        if do_fetch:
            self.fetch()

        return super().__setattr__(key, value)

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
            data = {k: v for k, v in data.items() if v is not None}

        return data

    def _update_properties(self, props, parse=True):
        for name, val in props.items():
            if name not in self.fields:
                #raise ValueError(f"Unknown field: {name}")
                continue

            field = self.fields[name]
            setattr(self, name, field.to_internal_value(self._gf, val) if parse else val)

        return self

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

        :param create: will create the object if it doesn't aleady exist. Otherwise saving a non-existing object \
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
        response = method(urljoin(self.endpoint, self.api_id) + "/" + params, json=self.to_json(include_derived=False),
                          expected_status=HTTPStatus.OK)
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
        obj = self._gf._get(urljoin(self.endpoint, self.api_id)).json()
        self._has_data = True
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

        return self._gf._delete(urljoin(self.endpoint, self.api_id))

    def __repr__(self):
        return str(self.to_json())


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


class WorkspaceMember(NestedMixin):
    """Stores information about a member of a workspace"""
    def __init__(self, username, membership_type):
        if username is None:
            raise ValueError("Username cannot be None")

        self.username = username
        self.membership_type = membership_type

    @classmethod
    def from_json(cls, data):
        return WorkspaceMember(username=data.get('username'),
                               membership_type=data.get('membership_type'))

    def to_json(self):
        return {'username': self.username,
                'membership_type': self.membership_type}

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


Recents = namedtuple("Recents", ["analyses", "figures"])


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


class gf_Workspace(ModelMixin, LogsMixin):
    """Represents a workspace"""
    # pylint: disable=protected-access

    fields = ["api_id",
              "name",
              "description",
              "workspace_type",
              LinkedEntityField("analyses", lambda gf: gf.Analysis, lazy=True, many=True, derived=True,
                                backlink_property='workspace')] + TIMESTAMP_FIELDS + CHILD_TIMESTAMP_FIELDS
    endpoint = "workspace/"

    def get_analysis(self, name, create=True, **kwargs):
        """\
        Finds an analysis by name.

        :param name: name of the analysis
        :param create: whether to create an analysis if one doesn't exist
        :param kwargs: if an Analysis needs to be created, parameters of the Analysis object (such as description)
        :return: Analysis instance.
        """
        return self.analyses.find_or_create(name=name,
                                            default_obj=self._gf.Analysis(name=name, **kwargs) if create else None)

    def get_members(self):
        """\
        Gets members of this workspace.

        :return: list of WorkspaceMember objects
        """
        response = self._gf._get(urljoin(self.endpoint, f'{self.api_id}/members/'),
                                  expected_status=HTTPStatus.OK)
        return [WorkspaceMember.from_json(datum) for datum in response.json()]

    def add_member(self, username, membership_type):
        """\
        Adds a member to this workspace.

        :param username: username of the person to add
        :param membership_type: WorkspaceMembership value, e.g. WorkspaceMembership.CREATOR
        :return: WorkspaceMember instance
        """
        response = self._gf._post(urljoin(self.endpoint, f'{self.api_id}/members/add/'),
                                  json=WorkspaceMember(username=username, membership_type=membership_type).to_json(),
                                  expected_status=HTTPStatus.OK)

        return WorkspaceMember.from_json(response.json())

    def change_membership(self, username, membership_type):
        """\
        Changes the membership level for a user.

        :param username: username
        :param membership_type: new membership type, e.g. WorkspaceMembership.CREATOR
        :return: WorkspaceMember instance

        """
        response = self._gf._post(urljoin(self.endpoint, f'{self.api_id}/members/change/'),
                                  json=WorkspaceMember(username=username, membership_type=membership_type).to_json(),
                                  expected_status=HTTPStatus.OK)

        return WorkspaceMember.from_json(response.json())

    def remove_member(self, username):
        """\
        Removes a member from this workspace.

        :param username: username
        :return: WorkspaceMember instance

        """
        response = self._gf._post(urljoin(self.endpoint, f'{self.api_id}/members/remove/'),
                                  json=WorkspaceMember(username=username, membership_type=None).to_json(),
                                  expected_status=HTTPStatus.OK)

        return WorkspaceMember.from_json(response.json())

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
        return Recents(analyses, figures)


class gf_Analysis(ShareableModelMixin, LogsMixin):
    """Represents an analysis"""
    # pylint: disable=protected-access

    fields = ["api_id",
              "name",
              "description",
              LinkedEntityField("workspace", lambda gf: gf.Workspace, lazy=True, many=False),
              LinkedEntityField("figures", lambda gf: gf.Figure, lazy=True, many=True, derived=True,
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
        return self.figures.find_or_create(name=name,
                                           default_obj=self._gf.Figure(name=name, **kwargs) if create else None)


class gf_Figure(ShareableModelMixin):
    """Represents a figure"""
    fields = ["api_id",
              "name",
              "description",
              LinkedEntityField("analysis", lambda gf: gf.Analysis, lazy=True, many=False),
              LinkedEntityField("revisions", lambda gf: gf.Revision, lazy=False, prefetched=True, many=True,
                                derived=True, backlink_property='figure')
              ] + TIMESTAMP_FIELDS + CHILD_TIMESTAMP_FIELDS
    endpoint = "figure/"


class DataType(abc.ABC):
    """\
    Enum for different types of data we can store inside a FigureRevision.
    """
    DATA_FRAME = "dataframe"
    CODE = "code"
    IMAGE = "image"
    TEXT = "text"


class MetadataProxy:
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
        if instance.metadata is None:
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


class Data(NestedMixin):
    """Represents binary data (e.g. image data, serialized dataframes, etc.)"""
    # pylint: disable=no-member

    SPECIALIZED_TYPES = None
    DATA_TYPE = None

    FIELDS = ["api_id", "name", "type", "metadata", "data"]

    def __init__(self, **kwargs):
        """\

        :param api_id: API ID of this data object
        :param name: name of this data object
        :param type: one of DataType values, e.g. DataType.IMAGE
        :param metadata: metadata dictionary
        :param data: binary data (bytes)
        """
        # Check data
        data = kwargs.get('data')
        if data is not None and not isinstance(data, bytes):
            raise ValueError(f"Data must be bytes, but got: {data.__class__}")

        self.type = kwargs.pop('type', self.DATA_TYPE)

        self.metadata = kwargs.pop('metadata', {})

        # Assign values to fields if supplied
        for name, value in kwargs.items():
            if name not in self.FIELDS and not hasattr(self, name):
                raise ValueError(f"{self.__class__.__name__} does not take a parameter named {name}")

            setattr(self, name, value)

        # If there are any unassigned fields, set to None
        for name in self.FIELDS:
            if not hasattr(self, name):
                setattr(self, name, None)

        # If there are any unassigned metadata fields, set to default
        for name, value in self.__class__.__dict__.items():
            if isinstance(value, MetadataProxy) and name not in self.metadata:
                setattr(self, name, value.default)

    def to_json(self):
        """\
        Converts this data object to JSON. Data will be base-64 encoded.

        :return:
        """
        res = {name: getattr(self, name) for name in self.FIELDS if name != 'data'}
        res['data'] = b64encode(self.data).decode('ascii') if self.data is not None else None
        return res

    @classmethod
    def from_json(cls, data):
        """\
        Parses a data object from JSON.

        :param data: JSON object
        :return: a specialized Data instance, e.g. ImageData
        """
        if cls.SPECIALIZED_TYPES is None:
            cls.SPECIALIZED_TYPES = Data.specialized_types()

        props = {name: data.get(name) for name in cls.FIELDS if name != 'data'}
        props['data'] = b64decode(data['data']) if 'data' in data else None
        return cls.SPECIALIZED_TYPES.get(data['type'], cls)(**props)

    @classmethod
    def specialized_types(cls):
        """\
        Lists all available Data subclasses, e.g. ImageData and CodeData

        :return: map of data type to specialized class
        """
        type_map = {}
        for _, obj in globals().items():
            if inspect.isclass(obj) and issubclass(obj, Data) and hasattr(obj, 'DATA_TYPE'):
                type_map[getattr(obj, 'DATA_TYPE')] = obj
        return type_map


class ImageData(Data):
    """Binary image data"""
    # pylint: disable=no-member

    DATA_TYPE = DataType.IMAGE

    is_watermarked = MetadataProxy("is_watermarked", default=False)
    format = MetadataProxy("format")

    @property
    def image(self):
        """\
        Returns this image as a PIL.Image object.

        :return: PIL.Image
        """
        if self.data is None:
            return None

        bio = io.BytesIO(self.data)
        img = PIL.Image.open(bio)
        img.load()
        return img


class CodeLanguage(abc.ABC):
    """\
    For code data objects, the programming language of the embedded code.
    """
    PYTHON = "Python"
    R = "R"


class CodeData(Data):
    """Serialized code data (it's text, but stored and transmitted as bytes)"""
    # pylint: disable=no-member

    DATA_TYPE = DataType.CODE

    language = MetadataProxy("language")
    format = MetadataProxy("format")
    encoding = MetadataProxy("encoding", default="utf-8")

    def __init__(self, contents=None, **kwargs):
        """\

        :param contents: code string. Will be encoded and stored internally as bytes.
        :param kwargs: same parameters as the Data constructor
        """
        super().__init__(**kwargs)
        if contents is not None:
            self.contents = contents

        self.format = "text"

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


class TextData(Data):
    """Serialized text data (even though it's text, we store and transmit bytes)"""
    # pylint: disable=no-member

    DATA_TYPE = DataType.TEXT
    encoding = MetadataProxy("encoding", default="utf-8")

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


class TableData(Data):
    """Serialized data frame"""
    # pylint: disable=no-member

    DATA_TYPE = DataType.DATA_FRAME

    format = MetadataProxy("format")
    encoding = MetadataProxy("encoding", default="utf-8")

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


class gf_Revision(ShareableModelMixin):
    """Represents a figure revision"""
    fields = ["api_id", "revision_index",
              JSONField("metadata"),
              LinkedEntityField("figure", lambda gf: gf.Figure, lazy=True, many=False),
              NestedEntityField("data", lambda gf: gf.Data, many=True),
              ] + TIMESTAMP_FIELDS

    endpoint = "revision/"

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

    @property
    def image_data(self):
        """Returns only image data (if any)"""
        return [dat for dat in self.data if dat.type == DataType.IMAGE]

    @image_data.setter
    def image_data(self, value):
        return self._replace_data_type(DataType.IMAGE, value)

    @property
    def table_data(self):
        """Returns only DataFrame data (if any)"""
        return [dat for dat in self.data if dat.type == DataType.DATA_FRAME]

    @table_data.setter
    def table_data(self, value):
        return self._replace_data_type(DataType.DATA_FRAME, value)

    @property
    def code_data(self):
        """Returns only code data (if any)"""
        return [dat for dat in self.data if dat.type == DataType.CODE]

    @code_data.setter
    def code_data(self, value):
        return self._replace_data_type(DataType.CODE, value)

    @property
    def text_data(self):
        """Returns only text data (if any)"""
        return [dat for dat in self.data if dat.type == DataType.TEXT]

    @text_data.setter
    def text_data(self, value):
        return self._replace_data_type(DataType.TEXT, value)

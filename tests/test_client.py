"""\
Copyright (c) 2022, Flagstaff Solutions, LLC
All rights reserved.

"""
import os
import time
from datetime import datetime, timedelta
from http import HTTPStatus
from unittest import TestCase

import numpy as np
import pandas as pd
import pkg_resources
from PIL import Image

from gofigr.models import gf_Data, MembershipInfo, OrganizationMembership, DataType

from gofigr import GoFigr, CodeLanguage, WorkspaceType, UnauthorizedError, ShareableModelMixin, WorkspaceMembership, \
    ThumbnailMixin, MethodNotAllowedError


def make_gf(authenticate=True, username=None, password=None, api_key=None):
    return GoFigr(username=username or (os.environ['GF_TEST_USER'] if api_key is None else None),
                  password=password or (os.environ['GF_TEST_PASSWORD'] if api_key is None else None),
                  api_key=api_key,
                  url=os.environ['GF_TEST_API_URL'],
                  authenticate=authenticate)


class TestAuthentication(TestCase):
    def test_successful_auth(self):
        gf = make_gf(authenticate=False)

        # Unauthenticated request should fail
        self.assertRaises(RuntimeError, lambda: self.assertEqual(gf.heartbeat()))

        self.assertTrue(gf.authenticate())
        self.assertEqual(gf.heartbeat().status_code, HTTPStatus.OK)

        # Re-authentication should work without errors
        self.assertTrue(gf.authenticate())
        self.assertEqual(gf.heartbeat().status_code, HTTPStatus.OK)

        self.assertTrue(gf.authenticate())
        self.assertEqual(gf.heartbeat().status_code, HTTPStatus.OK)

        self.assertTrue(gf.authenticate())
        self.assertEqual(gf.heartbeat().status_code, HTTPStatus.OK)

    def test_bad_password(self):
        # Incorrect user should fail
        bad_gf = make_gf(authenticate=False)
        bad_gf.password = bad_gf.password + "oops"
        self.assertRaises(RuntimeError, lambda: bad_gf.authenticate())
        self.assertRaises(RuntimeError, lambda: bad_gf.heartbeat())

    def test_bad_username(self):
        # Incorrect user should fail
        bad_gf = make_gf(authenticate=False)
        bad_gf.username = bad_gf.username + "oops"
        self.assertRaises(RuntimeError, lambda: bad_gf.authenticate())
        self.assertRaises(RuntimeError, lambda: bad_gf.heartbeat())

    def _cleanup(self):
        gf1 = make_gf(authenticate=True)
        gf2 = make_gf(authenticate=True, username=gf1.username + "2")

        # Revoke all keys (if any)
        for gf in [gf1, gf2]:
            for ak in gf.list_api_keys():
                gf.revoke_api_key(ak)

            for member in gf.primary_workspace.get_members():
                if member.username != gf.username:
                    gf.primary_workspace.remove_member(member.username)


    def setUp(self):
        self._cleanup()

    def tearDown(self):
        self._cleanup()

    def _list_workspaces_for_key(self, gf, api_key):
        gf_tok = make_gf(username=None, password=None, api_key=api_key.token, authenticate=True)
        return gf_tok.workspaces

    def _use_api_key(self, gf, api_key, workspace=None):
        if workspace is None:
            workspace = gf.primary_workspace

        # Create a client using the key
        gf_tok = make_gf(username=None, password=None, api_key=api_key.token, authenticate=True)

        self.assertEqual(gf_tok.username, gf.username)

        other_worx = gf_tok.Workspace(api_id=workspace.api_id).fetch()
        self.assertEqual(other_worx.api_id, workspace.api_id)
        self.assertEqual(other_worx.name, workspace.name)

        # Make sure we can create and modify objects
        ana = gf_tok.Analysis(name="Test analysis", workspace=workspace).create()

        ana.name = "Updated analysis"
        ana.save()
        ana.fetch()

        self.assertEqual(ana.name, "Updated analysis")

        # Make sure we can't revoke or create new keys when using API key authentication
        self.assertRaises(RuntimeError, lambda: gf_tok.create_api_key("should not work"))
        self.assertRaises(RuntimeError, lambda: gf_tok.revoke_api_key(api_key.api_id))

        ana.fetch()  # Try a fetch before we revoke the key
        return ana

    def test_api_key_authentication(self):
        gf = make_gf(authenticate=True)

        # Create an API key
        api_key = gf.create_api_key("test key")

        # Authenticate and perform some operations with the key
        ana = self._use_api_key(gf, api_key)

        # Revoke the key
        gf.revoke_api_key(api_key.api_id)

        # The token should no longer work
        self.assertRaises(RuntimeError, lambda: ana.fetch())

    def test_api_key_management(self):
        gf = make_gf(authenticate=True)

        # There should be no API keys yet
        self.assertEqual(len(gf.list_api_keys()), 0)

        key1 = gf.create_api_key('test key 1')
        key2 = gf.create_api_key('test key 2')

        self.assertEqual(key1.name, 'test key 1')
        self.assertEqual(key2.name, 'test key 2')

        # Token should be available at creation
        self.assertIsNotNone(key1.token)
        self.assertIsNotNone(key2.token)

        # Re-retrieve keys from server
        key1.name, key2.name = None, None
        key1.fetch()
        key2.fetch()
        self.assertEqual(key1.name, 'test key 1')
        self.assertEqual(key2.name, 'test key 2')

        # Token should no longer be available
        self.assertIsNone(key1.token)
        self.assertIsNone(key2.token)

        # Revoke key2
        gf.revoke_api_key(key2)
        self.assertEqual(len(gf.list_api_keys()), 1)
        self.assertEqual(gf.list_api_keys()[0].name, 'test key 1')

    def test_api_key_exclusivity(self):
        gf = make_gf(authenticate=True)
        gf2 = make_gf(authenticate=True, username=gf.username + "2")

        # Each user creates their own key
        key1 = gf.create_api_key('test key 1')
        key2 = gf2.create_api_key('test key 2')

        # They should only see their own keys
        self.assertEqual(len(gf.list_api_keys()), 1)
        self.assertEqual(gf.list_api_keys()[0].name, 'test key 1')
        self.assertEqual(len(gf2.list_api_keys()), 1)
        self.assertEqual(gf2.list_api_keys()[0].name, 'test key 2')

        # Trying to get info about other people's keys should fail
        self.assertRaises(RuntimeError, lambda: gf2.ApiKey(api_id=key1.api_id).fetch())
        self.assertRaises(RuntimeError, lambda: gf.ApiKey(api_id=key2.api_id).fetch())

    def test_api_key_expiration(self):
        gf = make_gf(authenticate=True)
        key1 = gf.create_api_key('test key 1', expiry=datetime.now() + timedelta(seconds=3))
        token = key1.token
        self._use_api_key(gf, key1)

        key1.fetch()  # this will set token to None (only available at creation), so we need to restore it
        key1.token = token
        self.assertIsNotNone(key1.expiry)

        # Wait for key to expire
        time.sleep(4)
        self.assertRaises(RuntimeError, lambda: self._use_api_key(gf, key1))

    def test_api_key_scopes(self):
        gf = make_gf(authenticate=True)
        worx2 = gf.Workspace(name="workspace 2").create()

        key_unscoped = gf.create_api_key('test key')
        key1 = gf.create_api_key('test key 1', workspace=gf.primary_workspace)
        key2 = gf.create_api_key('test key 2', workspace=worx2)

        self.assertIsNone(key_unscoped.fetch_and_preserve_token().workspace)
        self.assertEqual(key1.fetch_and_preserve_token().workspace.api_id, gf.primary_workspace.api_id)
        self.assertEqual(key2.fetch_and_preserve_token().workspace.api_id, worx2.api_id)

        # Unscoped key should work for both workspaces
        self._use_api_key(gf, key_unscoped, workspace=gf.primary_workspace)
        self._use_api_key(gf, key_unscoped, workspace=worx2)

        # Key 1 should only work for the primary workspace
        self._use_api_key(gf, key1, workspace=gf.primary_workspace)
        self.assertRaises(RuntimeError, lambda: self._use_api_key(gf, key1, workspace=worx2))

        # The workspace shouldn't be visible at all
        self.assertNotIn(worx2.api_id, [w.api_id for w in self._list_workspaces_for_key(gf, key1)])
        self.assertIn(gf.primary_workspace.api_id, [w.api_id for w in self._list_workspaces_for_key(gf, key1)])

        # Key 2 should only work for the second workspace
        self.assertRaises(RuntimeError, lambda: self._use_api_key(gf, key2, workspace=gf.primary_workspace))
        self._use_api_key(gf, key2, workspace=worx2)

        self.assertIn(worx2.api_id, [w.api_id for w in self._list_workspaces_for_key(gf, key2)])
        self.assertNotIn(gf.primary_workspace.api_id, [w.api_id for w in self._list_workspaces_for_key(gf, key2)])

    def test_api_key_scope_permissions(self):
        gf1 = make_gf(authenticate=True)
        gf2 = make_gf(authenticate=True, username=gf1.username + "2")

        # We should be unable to create keys with scopes in workspaces to which we don't have access
        self.assertRaises(RuntimeError,
                          lambda: gf1.create_api_key('test key 1', workspace=gf2.primary_workspace))
        self.assertRaises(RuntimeError,
                          lambda: gf2.create_api_key('test key 2', workspace=gf1.primary_workspace))

        # User 1 shares his workspace with User 2. User 2 should now be able to create a scoped key.
        gf1.primary_workspace.add_member(gf2.username, WorkspaceMembership.CREATOR)
        key2 = gf2.create_api_key('test key 2', workspace=gf1.primary_workspace)
        self._use_api_key(gf2, key2, gf1.primary_workspace)

        # User 1 unshares the workspace. Even though User's 2 key was created successfully, it should
        # no longer work
        gf1.primary_workspace.remove_member(gf2.username)
        self.assertRaises(RuntimeError, lambda: self._use_api_key(gf2, key2, gf1.primary_workspace))


class TestUsers(TestCase):
    def test_user_info(self):
        gf = make_gf()
        info = gf.user_info()
        self.assertEqual(gf.user_info(), gf.user_info(gf.username))
        self.assertEqual(info.username, gf.username)
        self.assertIn(info.email, ['testuser@server.com', 'testuser@gofigr.io'])

        # Update first and last names
        for first, last in [("a", "b"), ("", ""), ("Test", "User")]:
            info.first_name = first
            info.last_name = last
            gf.update_user_info(info)

            info = gf.user_info()
            self.assertEqual(info.first_name, first)
            self.assertEqual(info.last_name, last)

        # We should not be able to change the username
        info.username = "another_user"
        self.assertRaises(UnauthorizedError, lambda: gf.update_user_info(info, username=gf.username))
        self.assertEqual(gf.user_info().username, gf.username)

        # We should not be able to change to staff
        info = gf.user_info()
        info.is_staff = True
        gf.update_user_info(info)
        self.assertFalse(gf.user_info().is_staff)

        # We should not be able to change info for anyone else
        for other_user in ['testuser2']:
            info.username = other_user
            self.assertRaises(UnauthorizedError, lambda: gf.update_user_info(info))

    def test_user_profile(self):
        gf = make_gf()
        info = gf.user_info()
        info.user_profile = {'ui_data': {}}
        gf.update_user_info(info)

        info = gf.user_info()
        self.assertEqual(info.user_profile['ui_data'], {})

        info.user_profile = {'ui_data': {'hello': 'world', 'foo': 'bar', 'baz': [1, 2, 3]}}
        gf.update_user_info(info)
        info = gf.user_info()
        self.assertEqual(info.user_profile['ui_data']['hello'], 'world')
        self.assertEqual(info.user_profile['ui_data']['foo'], 'bar')
        self.assertListEqual(info.user_profile['ui_data']['baz'], [1, 2, 3])

        info.user_profile = {'ui_data': {'foo': 'barz', 'baz': [3, 2, 1]}}
        gf.update_user_info(info)
        info = gf.user_info()
        self.assertNotIn('hello', info.user_profile['ui_data'])
        self.assertEqual(info.user_profile['ui_data']['foo'], 'barz')
        self.assertListEqual(info.user_profile['ui_data']['baz'], [3, 2, 1])

    def test_avatars(self):
        gf = make_gf()
        info = gf.user_info()
        with open(pkg_resources.resource_filename('tests.data', 'avatar.png'), 'rb') as f:
            info.avatar = Image.open(f)
            info.avatar.load()

        gf.update_user_info(info)


class TestWorkspaces(TestCase):
    def clean_up(self):
        # Delete all workspaces for the test user
        gf = make_gf()
        for w in gf.Workspace.list():
            if w.workspace_type != "primary":
                w.delete(delete=True)

        # Reset primary workspace
        gf.primary_workspace.name = "Primary workspace"
        gf.primary_workspace.description = "Primary workspace description"
        gf.primary_workspace.save()

        # Delete all analyses under primary workspace
        for ana in gf.primary_workspace.analyses:
            ana.delete(delete=True)

    def setUp(self):
        return self.clean_up()

    def tearDown(self):
        return self.clean_up()

    def test_listing(self):
        gf = make_gf()
        workspaces = [w for w in gf.workspaces if w.workspace_type == "primary"]

        self.assertEqual(len(workspaces), 1)
        w, = workspaces

        # Should be the user's primary workspace
        self.assertEqual(w.workspace_type, "primary")
        self.assertIsNotNone(w.api_id)
        self.assertTrue("primary" in w.name.lower())
        self.assertTrue("primary" in w.description.lower())

    def test_updates(self):
        gf = make_gf()
        workspace = gf.Workspace(name="test workspace", workspace_type=WorkspaceType.SECONDARY).create()

        # Add a few analyses
        for idx in range(10):
            workspace.analyses.create(gf.Analysis(name=f"Analysis {idx}"))

        self.assertEqual(len(workspace.analyses), 10)

        workspace.name = "new name"
        workspace.description = "new description"
        workspace.save()

        workspace2 = gf.Workspace(workspace.api_id).fetch()
        self.assertEqual(workspace, workspace2)
        for w in [workspace, workspace2]:
            self.assertEqual(w.name, "new name")
            self.assertEqual(w.description, "new description")

        _test_timestamps(self, gf, workspace, 'name', ['a', 'b', 'c'])

    def test_creation(self, n_workspaces=10):
        gf = make_gf()

        for widx in range(n_workspaces):
            w = gf.Workspace(name=f"Test workspace {widx}", description=f"Custom workspace #{widx}",
                             workspace_type=WorkspaceType.SECONDARY)
            w = w.create()
            self.assertIsNotNone(w.api_id)

            w = gf.Workspace(name=f"Test workspace {widx}", description=f"Custom workspace #{widx}",
                             workspace_type="invalid workspace type")
            self.assertRaises(RuntimeError, lambda: w.create())

        workspaces = gf.workspaces
        self.assertEqual(len(workspaces), n_workspaces + 1)  # +1 because of the primary workspace
        self.assertGreaterEqual(len(workspaces), n_workspaces + 1)

    def test_primary_workspace_not_creatable(self):
        gf = make_gf()

        w = gf.Workspace(name=f"Primary workspace", description=f"primary",
                         workspace_type=WorkspaceType.PRIMARY)
        self.assertRaises(RuntimeError, lambda: w.create())

        # Make sure we cannot change a primary workspace to secondary
        pw = gf.primary_workspace
        try:
            pw.workspace_type = WorkspaceType.SECONDARY
            self.assertRaises(RuntimeError, lambda: pw.save())
        finally:
            pw.workspace_type = WorkspaceType.PRIMARY
            pw.save()

        # Also make sure we can't change secondary -> primary
        w = gf.Workspace(name="workspace", workspace_type=WorkspaceType.SECONDARY)
        w.create()

        try:
            w.workspace_type = WorkspaceType.PRIMARY
            self.assertRaises(RuntimeError, lambda: w.save())
        finally:
            w.delete(delete=True)

    def test_recents(self):
        gf = make_gf()

        for widx in range(2):
            w = gf.Workspace(name=f"Workspace {widx}").create()

            for aidx in range(2):
                a = w.analyses.create(gf.Analysis(name=f"Analysis {aidx}"))

                for fidx in range(3):
                    fig = gf.Figure(name=f"Analysis {aidx} -> Figure {fidx}")
                    a.figures.create(fig)

            recents = w.get_recents()
            self.assertEqual(len(recents.analyses), 2)
            self.assertEqual(len(recents.figures), 6)

            self.assertEqual([ana.name for ana in recents.analyses],
                             ["Analysis 1", "Analysis 0"])

            self.assertEqual([fig.name for fig in recents.figures],
                             ["Analysis 1 -> Figure 2",
                              "Analysis 1 -> Figure 1",
                              "Analysis 1 -> Figure 0",
                              "Analysis 0 -> Figure 2",
                              "Analysis 0 -> Figure 1",
                              "Analysis 0 -> Figure 0"])


def _test_timestamps(test_case, gf, obj, prop_name, vals, delay_seconds=0.5):
    last_update = datetime.now().astimezone() if obj.updated_on is None else obj.updated_on

    for val in vals:
        time.sleep(delay_seconds)
        obj.fetch()

        setattr(obj, prop_name, val)
        obj.save()

        server_obj = obj.__class__(api_id=obj.api_id).fetch()

        # We're not too strict about creation time, but all these objects are created
        # in the unit test and should be fairly recent (~1min)
        test_case.assertLess(datetime.now().astimezone() - obj.created_on,
                             timedelta(seconds=120))
        test_case.assertEqual(obj.created_by, gf.username)

        test_case.assertEqual(server_obj.updated_by, gf.username)
        test_case.assertGreaterEqual(server_obj.updated_on - last_update, timedelta(seconds=delay_seconds))
        test_case.assertLess(server_obj.updated_on - last_update, timedelta(seconds=delay_seconds + 20))
        last_update = server_obj.updated_on


class TestAnalysis(TestCase):
    def tearDown(self):
        gf = make_gf()
        for analysis in gf.primary_workspace.analyses:
            analysis.delete(delete=True)

    def test_creation(self, n_analyses=10):
        gf = make_gf()
        workspace = gf.primary_workspace

        for idx in range(n_analyses):
            analysis = gf.Analysis(name=f"Analysis #{idx}", description=f"Description #{idx}")
            workspace.analyses.create(analysis)
            self.assertLess(datetime.now().astimezone() - analysis.created_on, timedelta(seconds=5))
            self.assertIsNone(analysis.updated_on)

            # Make sure the analysis is now associated with the workspace object
            refreshed_workspace = gf.Workspace(workspace.api_id).fetch()
            analysis_ids = [x.api_id for x in refreshed_workspace.analyses]
            self.assertIn(analysis.api_id, analysis_ids)

            # Refetch from ID to make sure it was persisted
            server_analysis = gf.Analysis(analysis.api_id).fetch()

            self.assertEqual(analysis.api_id, server_analysis.api_id)
            self.assertEqual(analysis.name, server_analysis.name)
            self.assertEqual(analysis.description, server_analysis.description)
            self.assertEqual(analysis.created_on, server_analysis.created_on)
            self.assertEqual(analysis.created_by, server_analysis.created_by)
            self.assertEqual(analysis.updated_on, server_analysis.updated_on)
            self.assertEqual(analysis.updated_by, server_analysis.updated_by)

    def test_updates(self):
        gf = make_gf()
        workspace = gf.primary_workspace
        analysis = workspace.analyses.create(gf.Analysis(name=f"Pre-update name", description='Pre-update description'))

        analysis.name = "Post-update name"
        analysis.save()

        analysis2 = gf.Analysis(analysis.api_id).fetch()

        for ana in [analysis, analysis2]:
            self.assertEqual(ana.name, "Post-update name")
            self.assertEqual(ana.description, "Pre-update description")
            self.assertEqual(ana.workspace.fetch(), workspace)

        analysis2.name = "another name"
        analysis2.description = "another description"
        analysis2.save()
        analysis.fetch()  # refresh

        for ana in [analysis, analysis2]:
            self.assertEqual(ana.name, "another name")
            self.assertEqual(ana.description, "another description")
            self.assertEqual(ana.workspace.fetch(), workspace)

        # Assign to a new workspace
        new_workspace = gf.Workspace(name="New workspace", description="abc").create()
        self.assertEqual(len(new_workspace.analyses), 0)

        analysis.workspace = new_workspace
        analysis.save()

        # Refresh list of analyses
        workspace.fetch()
        new_workspace.fetch()

        self.assertEqual(len(workspace.analyses), 0)
        self.assertEqual(len(new_workspace.analyses), 1)

        new_workspace.analyses[0].fetch()
        self.assertEqual(new_workspace.analyses[0], analysis)

        _test_timestamps(self, gf, analysis, 'description', ['a', 'b', 'c', 'd'])

    def test_partial_update(self):
        gf = make_gf()
        workspace = gf.primary_workspace
        analysis = workspace.analyses.create(gf.Analysis(name=f"Test analysis", description='Test description'))

        updated_analysis = gf.Analysis(api_id=analysis.api_id, description="New description")
        updated_analysis.save(patch=True)

        analysis.fetch()
        self.assertEqual(analysis.name, "Test analysis")
        self.assertEqual(analysis.description, "New description")
        self.assertEqual(analysis.workspace.fetch(), gf.primary_workspace)


class TestData:
    def __init__(self, gf):
        self.gf = gf

    def load_image_data(self, nonce=None):
        image_data = []
        for fmt in ['eps', 'svg', 'png']:
            with open(pkg_resources.resource_filename('tests.data', f'plot.{fmt}'), 'rb') as f:
                _data = f.read()
                if nonce is not None:
                    _data = _data + str(nonce).encode('ascii')

                image_data.append(self.gf.ImageData(name="test image", format=fmt, data=_data,
                                                    is_watermarked=(fmt == 'eps')))
        return image_data

    def load_file_data(self, nonce=None):
        data_obj = self.gf.FileData.read(pkg_resources.resource_filename('tests.data', 'blob.bin'))
        data_obj.data = data_obj.data + str(nonce).encode('ascii')
        return [data_obj]

    def load_code_data(self, nonce=None):
        with open(__file__, 'r') as f:
            return [self.gf.CodeData(name="test code",
                                     language=CodeLanguage.PYTHON,
                                     contents="hello world" + (str(nonce) or "")),
                    self.gf.CodeData(name=__file__,
                                     language=CodeLanguage.PYTHON,
                                     contents=f.read() + (str(nonce) or ""))]

    def load_table_data(self, nonce=None):
        frame1 = pd.DataFrame({
            "ordinal": np.arange(100),
            "name": ["foo", "bar", "baz", "foobar"] * 25,
            "date": datetime.now(),
            "randoms": np.random.normal(size=100),
            "nonce": [nonce] * 100,
        })

        frame2 = pd.DataFrame({
            "number": np.arange(1000),
            "word": ["hello", "world", "how", "are", "you"] * 200,
            "time": datetime.now(),
            "normals": np.random.normal(size=1000, loc=-20, scale=100),
            "nonce2": [nonce] * 1000,
        })
        return [self.gf.TableData(name="small table", dataframe=frame1),
                self.gf.TableData(name="large table", dataframe=frame2)]

    def load_external_data(self, nonce=None):
        return self.load_image_data(nonce) + self.load_table_data(nonce) + self.load_code_data(nonce) + \
            self.load_file_data(nonce)


class GfTestCase(TestCase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.gf = make_gf()

    def setUp(self):
        return self.clean_up()

    def tearDown(self):
        return self.clean_up()

    def clean_up(self):
        gf = self.gf

        gf.primary_workspace.organization = None
        gf.primary_workspace.save()

        for ana in gf.primary_workspace.analyses:
            ana.delete(delete=True)

        for ds in gf.primary_workspace.assets:
            ds.delete(delete=True)

        for w in gf.workspaces:
            if w.workspace_type != WorkspaceType.PRIMARY:
                w.delete(delete=True)

        for org in gf.organizations:
            org.delete(delete=True)


class TestFigures(TestCase):
    def setUp(self):
        return self.clean_up()

    def tearDown(self):
        return self.clean_up()

    def clean_up(self):
        gf = make_gf()
        for ana in gf.primary_workspace.analyses:
            ana.delete(delete=True)

        for w in gf.workspaces:
            if w.workspace_type != WorkspaceType.PRIMARY:
                w.delete(delete=True)

    def test_creation(self, n_analyses=3, n_figures=5):
        gf = make_gf()
        anas = [gf.primary_workspace.analyses.create(gf.Analysis(name=f"My analysis{idx}"))
                for idx in range(n_analyses)]

        # Create a bunch of figures
        expected_names = set()
        for ana in anas:
            for idx in range(n_figures):
                name = f"Test figure #{idx}"
                ana.figures.create(gf.Figure(name=name))
                expected_names.add(name)

        # Recreate from server and make sure we see the newly created figures
        for ana in anas:
            ana_srv = gf.Analysis(ana.api_id).fetch()
            self.assertEqual(len(ana_srv.figures), n_figures)

            for idx, fig in enumerate(ana_srv.figures):
                self.assertIsNone(fig.updated_on)
                self.assertIn(fig.name, expected_names)

                _test_timestamps(self, gf, fig, 'name', ['a', 'b', 'c'])

    def test_timestamp_propagation(self):
        gf = make_gf()
        workspace = gf.Workspace(name="test workspace").create()
        ana = workspace.analyses.create(gf.Analysis(name="test analysis 1"))
        fig = ana.figures.create(gf.Figure(name="my test figure"))

        for idx in range(5):
            time.sleep(0.05)
            rev = gf.Revision(metadata={'index': idx},
                              data=TestData(gf).load_external_data(nonce=idx))
            rev = fig.revisions.create(rev)

            for parent in [fig, ana, workspace]:
                parent.fetch()
                self.assertEqual(parent.child_updated_on, rev.created_on)
                self.assertEqual(parent.child_updated_by, rev.created_by)

            time.sleep(0.05)
            rev.metadata = {'updated': 'yay'}
            rev.save()

            for parent in [fig, ana, workspace]:
                parent.fetch()
                self.assertNotEqual(parent.child_updated_on, rev.created_on)
                self.assertEqual(parent.child_updated_on, rev.updated_on)
                self.assertEqual(parent.child_updated_by, rev.updated_by)

            time.sleep(0.05)
            deletion_time = datetime.now().astimezone()
            rev.delete(delete=True)

            for parent in [fig, ana, workspace]:
                parent.fetch()
                self.assertGreaterEqual(parent.child_updated_on, deletion_time)
                self.assertEqual(parent.child_updated_by, gf.username)

        # Check logs
        logs = [log.fetch() for log in workspace.get_logs()]
        self.assertEqual(len(logs), 18)  # 18 = create x3 (workspace+analysis+fig) + (create, update, delete) x 5 revisions
        for item in logs:
            self.assertIn(item.action, ["create", "update", "delete"])
            self.assertLessEqual((datetime.now().astimezone() - item.timestamp).total_seconds(), 120)

    def test_revisions(self):
        def _order_data(data):
            return sorted(data, key=lambda d: str(d.data))

        gf = make_gf()
        workspace = gf.Workspace(name="test workspace").create()
        ana = workspace.analyses.create(gf.Analysis(name="test analysis 1"))
        fig = ana.figures.create(gf.Figure(name="my test figure"))

        revisions = []
        for idx in range(5):
            rev = gf.Revision(metadata={'index': idx},
                              data=TestData(gf).load_external_data(nonce=idx))

            rev = fig.revisions.create(rev)
            fig.fetch()  # to update timestamps
            ana.fetch()  # ...

            self.assertIsNotNone(rev.image_data)

            # Validate general revision metadata
            # Fetch the server revision in 2 different ways: (1) directly using API ID, and (2) through the figure
            server_rev1 = gf.Revision(rev.api_id).fetch()

            server_rev2, = [x for x in gf.Figure(fig.api_id).fetch().revisions if x.api_id == rev.api_id]

            # server_rev2 is a shallow copy, so fetch everything here
            server_rev2.fetch()

            for server_rev in [server_rev1, server_rev2]:
                # Fetch all data objects
                self.assertEqual(server_rev.metadata, {'index': idx})
                self.assertEqual(server_rev.figure.fetch(), fig)
                self.assertEqual(server_rev.figure.analysis.fetch(), ana)

                # Validate image data
                for data_getter, expected_length, fields_to_check in \
                    [(lambda r: _order_data(r.image_data), 3, ["name", "data", "is_watermarked", "format"]),
                     (lambda r: _order_data(r.code_data), 2, ["name", "data", "language", "contents"]),
                     (lambda r: _order_data(r.table_data), 2, ["name", "data", "format", "dataframe"]),
                     (lambda r: _order_data(r.file_data), 1, ["name", "data", "path"])]:
                    self.assertEqual(len(data_getter(server_rev)), expected_length)
                    for img, srv_img in zip(data_getter(rev), data_getter(server_rev)):
                        for field_name in fields_to_check:
                            if field_name == 'dataframe':
                                self.assertTrue(getattr(img, field_name).equals(getattr(srv_img, field_name)))
                            else:
                                self.assertEqual(getattr(img, field_name), getattr(srv_img, field_name))

            # Tweaking of figure metadata should in no way affect data contents
            fig.name = f"my test figure {idx}"
            fig.save()

            # Update data
            server_rev.image_data = [gf.ImageData(name="updated image", format=img.format,
                                                  data="updated".encode('ascii'), is_watermarked=True)
                                     for img in server_rev.image_data]

            server_rev.table_data = [gf.TableData(name="updated table", format=table.format,
                                                  data="updated".encode('ascii'))
                                     for table in server_rev.table_data]

            server_rev.code_data = [gf.CodeData(name="updated code", format=code.format,
                                                language=code.language,
                                                data="updated".encode('ascii'))
                                    for code in server_rev.code_data]

            server_rev.file_data = [gf.FileData(name="updated file",
                                                data="updated".encode('ascii'))
                                    for code in server_rev.code_data]

            server_rev.save()
            server_rev = gf.Revision(rev.api_id).fetch()

            for img in server_rev.image_data:
                self.assertEqual(img.name, "updated image")
                self.assertEqual(img.data, "updated".encode('ascii'))

            for table in server_rev.table_data:
                self.assertEqual(table.name, "updated table")
                self.assertEqual(table.data, "updated".encode('ascii'))

            for code in server_rev.code_data:
                self.assertEqual(code.name, "updated code")
                self.assertEqual(code.data, "updated".encode('ascii'))

            for code in server_rev.file_data:
                self.assertEqual(code.name, "updated file")
                self.assertEqual(code.data, "updated".encode('ascii'))

            _test_timestamps(self, gf, rev, 'metadata', ['a', 'b', 'c'])

            revisions.append(rev)

        fig.fetch()
        self.assertEqual(len(fig.revisions), 5)

        # Delete revisions
        for rev in fig.revisions:
            rev.delete(delete=True)

        # Delete the analysis
        ana.delete(delete=True)


class MultiUserTestCaseBase:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.n_revisions = 2

    def create_test_analysis(self, gf, workspace):
        ana = workspace.analyses.create(gf.Analysis(name=f"{gf.username}'s test analysis"))
        fig = ana.figures.create(gf.Figure(name=f"{gf.username}'s test figure"))

        for idx in range(self.n_revisions):
            rev = gf.Revision(metadata={'index': idx},
                              data=TestData(gf).load_external_data(nonce=idx))
            fig.revisions.create(rev)

        return ana

    def setUp(self):
        self.gf1 = make_gf(username="testuser")
        self.gf2 = make_gf(username="testuser2")
        self.clients = [self.gf1, self.gf2]
        self.client_pairs = [(self.gf1, self.gf2)]

        # Clean up old data (if any)
        self.clean_up()

        # Set up test data for each user
        for gf in self.clients:
            test_workspace = gf.Workspace(name=f"{gf.username}'s test workspace").create()

            for workspace in [test_workspace, gf.primary_workspace]:
                self.create_test_analysis(gf, workspace)

    def tearDown(self):
        return self.clean_up()

    def clean_up(self):
        for gf in self.clients:
            gf.primary_workspace.organization = None
            gf.primary_workspace.save()

            for w in gf.workspaces:
                w.fetch()  # Refresh
                if w.workspace_type != WorkspaceType.PRIMARY:
                    w.delete(delete=True)
                else:
                    for ana in w.analyses:
                        ana.delete(delete=True)

                    for ds in w.assets:
                        ds.delete(delete=True)

                    for member in w.get_members():
                        if member.membership_type != "owner":
                            w.remove_member(member.username)

            for org in gf.organizations:
                org.delete(delete=True)

    def get_gf_type(self, obj, client):
        return getattr(client, type(obj)._gofigr_type_name)

    def list_data_objects(self, workspace):
        for obj in self.list_workspace_objects(workspace):
            if isinstance(obj, gf_Data):
                yield obj

    def list_workspace_objects(self, workspace, include_self=True):
        if include_self:
            yield workspace

        for analysis in workspace.analyses:
            analysis.fetch()
            yield analysis

            for fig in analysis.figures:
                fig.fetch()
                yield fig

                for rev in fig.revisions:
                    rev.fetch()
                    yield rev
                    yield from rev.data

    def list_all_objects(self, gf):
        for org in gf.organizations:
            yield org

        for workspace in gf.workspaces:
            yield from self.list_workspace_objects(workspace)


    def clone_gf_object(self, obj, client, bare=False):
        cloned_obj = self.get_gf_type(obj, client)(api_id=obj.api_id)

        if not bare:
            for fld in obj.fields:
                setattr(cloned_obj, fld, getattr(obj, fld))

        return cloned_obj

    def assert_exclusivity(self):
        for client, other_client in self.client_pairs:
            for own_obj in self.list_all_objects(client):
                own_obj.fetch()  # own_obj may be a shallow copy, so fetch everything first

                not_own_obj = self.clone_gf_object(own_obj, other_client)

                # VIEW
                with self.assertRaises(UnauthorizedError, msg=f"Unauthorized view access granted to {own_obj}"):
                    not_own_obj.fetch()

                if isinstance(not_own_obj, ThumbnailMixin):
                    with self.assertRaises(UnauthorizedError, msg=f"Unauthorized thumbnail access granted to {own_obj}"):
                        not_own_obj.get_thumbnail(256)

                # DELETE
                with self.assertRaises(MethodNotAllowedError if isinstance(not_own_obj, gf_Data) else UnauthorizedError,
                                       msg=f"Unauthorized delete granted to {own_obj}"):
                    not_own_obj.delete(delete=True)

                # UPDATE
                if hasattr(own_obj, 'name'):
                    not_own_obj.name = "gotcha"
                elif hasattr(own_obj, 'metadata'):
                    not_own_obj.metadata = {'gotcha': 'oops'}
                else:
                    raise ValueError(f"Don't know how to update {not_own_obj}")

                for patch in [False, True]:
                    with self.assertRaises(MethodNotAllowedError \
                                                   if isinstance(not_own_obj, gf_Data) \
                                                   else UnauthorizedError,
                                           msg=f"Unauthorized update granted on {own_obj}"):
                        not_own_obj.save(patch=patch)

                # Make sure the properties didn't actually change
                own_obj2 = self.clone_gf_object(own_obj, client, bare=True).fetch()
                self.assertEqual(str(own_obj.to_json()), str(own_obj2.to_json()))


class MultiUserTestCase(MultiUserTestCaseBase, TestCase):
    pass


class TestPermissions(MultiUserTestCase):
    def test_exclusivity(self):
        return self.assert_exclusivity()

    def test_malicious_move(self):
        for client, other_client in self.client_pairs:
            # Case 1: user moving their analyses (to which they have access) to another users' workspace (to which
            # they do not have access)
            for w in client.workspaces:
                for ana in w.analyses:
                    ana.fetch()
                    ana.workspace = other_client.primary_workspace

                    for patch in [False, True]:
                        with self.assertRaises(UnauthorizedError,
                                               msg=f"Unauthorized move granted on: {ana} -> {ana.workspace}"):
                            ana.save(patch=patch)

                    # Likewise with figures
                    for fig in ana.figures:
                        fig.fetch()
                        fig.analysis = other_client.primary_workspace.analyses[0]

                        for patch in [False, True]:
                            with self.assertRaises(UnauthorizedError,
                                                   msg=f"Unauthorized move granted on: {fig} -> {fig.analysis}"):
                                fig.save(patch=patch)

            # Case 2: user moving others' analyses (to which they don't have access) into their own workspace
            # (to which they do)
            for w in other_client.workspaces:
                for ana in w.analyses:
                    ana.fetch()
                    ana.workspace = client.primary_workspace

                    for patch in [False, True]:
                        with self.assertRaises(UnauthorizedError,
                                               msg=f"Unauthorized move granted on: {ana} -> {ana.workspace}"):
                            ana.save(patch=patch)

                    # Same with figures
                    for fig in ana.figures:
                        fig.fetch()
                        fig.analysis = client.primary_workspace.analyses[0]

                        for patch in [False, True]:
                            with self.assertRaises(UnauthorizedError,
                                                   msg=f"Unauthorized move granted on: {fig} -> {fig.analysis}"):
                                fig.save(patch=patch)

    def test_malicious_create(self):
        for client, other_client in self.client_pairs:
            # Attempt to create analyses and figures in workspaces that you do not control
            for w in client.workspaces:
                for ana in w.analyses:
                    ana.fetch()
                    new_ana = self.clone_gf_object(ana, other_client)
                    new_ana.api_id = None  # pretend it's a new object

                    with self.assertRaises(UnauthorizedError, msg="Unauthorized create"):
                        new_ana.create()

                    for fig in ana.figures:
                        new_fig = self.clone_gf_object(fig, other_client)
                        new_fig.api_id = None

                        with self.assertRaises(UnauthorizedError, msg="Unauthorized create"):
                            new_fig.create()


class TestSharing(MultiUserTestCase):
    """\
    Tests sharing. Note that the actual sharing logic is tested extensively on the backend, so this is
    just a quick API test.

    """
    def test_sharing(self):
        def _check_one(other_client, obj):
            obj.fetch()  # in case it's just a shallow copy

            # Not shared by default
            self.assertRaises(UnauthorizedError,
                              lambda: self.clone_gf_object(obj, other_client, bare=True).fetch())

            # Share with this specific user. Should be viewable now.
            obj.share(other_client.username)
            shared_obj = self.clone_gf_object(obj, other_client, bare=True).fetch()
            self.assertEqual(obj, shared_obj)

            # However, the object should NOT be modifiable
            if hasattr(shared_obj, 'name'):
                shared_obj.name = 'i should not be able to do this'
                self.assertRaises(UnauthorizedError, lambda: shared_obj.save())

            self.assertEqual(len(obj.get_sharing_users()), 1)
            self.assertEqual(obj.get_sharing_users()[0].username, other_client.username)

            # Even though the object is shared, the user it's shared with should not be able to view who else
            # it's shared with.
            self.assertRaises(UnauthorizedError, lambda: self.clone_gf_object(obj, other_client).get_sharing_users())

            # Unshare
            obj.unshare(other_client.username)
            time.sleep(2)

            self.assertRaises(UnauthorizedError,
                              lambda: self.clone_gf_object(obj, other_client, bare=True).fetch())
            self.assertEqual(len(obj.get_sharing_users()), 0)

            # Double unshare
            obj.unshare(other_client.username)
            self.assertRaises(UnauthorizedError,
                              lambda: self.clone_gf_object(obj, other_client, bare=True).fetch())
            self.assertEqual(len(obj.get_sharing_users()), 0)

            # Turn on link sharing
            obj.set_link_sharing(True)
            shared_obj = self.clone_gf_object(obj, other_client, bare=True).fetch()
            self.assertEqual(obj, shared_obj)
            self.assertEqual(len(obj.get_sharing_users()), 0)
            self.assertRaises(UnauthorizedError, lambda: self.clone_gf_object(obj, other_client).get_sharing_users())

            # Turn off link sharing
            obj.set_link_sharing(False)
            time.sleep(2)

            self.assertRaises(UnauthorizedError,
                              lambda: self.clone_gf_object(obj, other_client, bare=True).fetch())
            self.assertEqual(len(obj.get_sharing_users()), 0)

        for client, other_client in self.client_pairs:
            for obj in self.list_all_objects(client):
                if not isinstance(obj, ShareableModelMixin):
                    continue

                for _ in range(2):  # Sharing/unsharing cycles are indempotent
                    _check_one(other_client, obj)
                    time.sleep(2)

                # Sharing with a non-existent user
                self.assertRaises(RuntimeError, lambda: obj.share("no_such_user_exists"))
                self.assertRaises(RuntimeError, lambda: obj.unshare("no_such_user_exists"))

        # Nothing should be shared now
        self.assert_exclusivity()

    def test_workspaces_not_shareable(self):
        """Makes sure that workspaces are not shareable"""
        for client, other_client in self.client_pairs:
            # Workspaces are not ShareableModelMixins to prevent exactly this, but we pretend they are.
            # The request should be rejected server-side.
            self.assertRaises(RuntimeError,
                              lambda: ShareableModelMixin.share(client.primary_workspace, other_client.username))
            self.assertRaises(RuntimeError,
                              lambda: ShareableModelMixin.set_link_sharing(client.primary_workspace, True))
            self.assertRaises(RuntimeError,
                              lambda: ShareableModelMixin.get_link_sharing(client.primary_workspace))

    def test_malicious_sharing(self):
        """Makes sure that users cannot share other people's objects with themselves"""
        for client, other_client in self.client_pairs:
            for obj in self.list_all_objects(client):
                if not isinstance(obj, ShareableModelMixin):
                    continue

                # Other client creates a reference to this object, and attempts to share it with themselves
                obj_ref = self.clone_gf_object(obj, other_client)
                self.assertRaises(UnauthorizedError, lambda: obj_ref.share(other_client.username))
                self.assertRaises(UnauthorizedError, lambda: obj_ref.set_link_sharing(True))
                self.assertRaises(UnauthorizedError, lambda: obj_ref.fetch())

        self.assert_exclusivity()


class TestWorkspaceMemberManagement(MultiUserTestCase):
    def test_member_management(self):
        for client, other_client in self.client_pairs:
            for workspace in client.workspaces:
                for lvl in [WorkspaceMembership.ADMIN, WorkspaceMembership.CREATOR, WorkspaceMembership.VIEWER]:
                    workspace.add_member(other_client.username, lvl)
                    self.assertEqual(len(workspace.get_members()), 2)
                    self.assertIn(client.username, [m.username for m in workspace.get_members()])
                    self.assertIn(other_client.username, [m.username for m in workspace.get_members()])

                    member, = [m for m in workspace.get_members() if m.username == other_client.username]
                    self.assertEqual(member.membership_type, lvl)

                    workspace.remove_member(other_client.username)
                    self.assertEqual(len(workspace.get_members()), 1)
                    self.assertIn(client.username, [m.username for m in workspace.get_members()])
                    self.assertNotIn(other_client.username, [m.username for m in workspace.get_members()])

                # Adding a new owner should fail
                self.assertRaises(RuntimeError, lambda: workspace.add_member(other_client.username,
                                                                             WorkspaceMembership.OWNER))

                # Likewise, changing an existing user to owner
                workspace.add_member(other_client.username, WorkspaceMembership.ADMIN)
                self.assertRaises(RuntimeError, lambda: workspace.change_membership(other_client.username,
                                                                                    WorkspaceMembership.OWNER))

                # But changing to anything else should work
                for lvl in [WorkspaceMembership.ADMIN, WorkspaceMembership.CREATOR, WorkspaceMembership.VIEWER]:
                    workspace.change_membership(other_client.username, lvl)
                    self.assertEqual(len(workspace.get_members()), 2)
                    self.assertIn(client.username, [m.username for m in workspace.get_members()])
                    self.assertIn(other_client.username, [m.username for m in workspace.get_members()])

                    member, = [m for m in workspace.get_members() if m.username == other_client.username]
                    self.assertEqual(member.membership_type, lvl)

    def test_malicious_add(self):
        for client, other_client in self.client_pairs:
            for workspace in client.workspaces:
                # Workspace accessed by the other client
                workspace_ref = self.clone_gf_object(workspace, other_client)

                self.assertRaises(UnauthorizedError, lambda: workspace_ref.add_member(other_client.username,
                                                                                      WorkspaceMembership.ADMIN))

                # This should fail even if the user is already a member with a level below ADMIN
                workspace.add_member(other_client.username, WorkspaceMembership.CREATOR)
                self.assertRaises(UnauthorizedError, lambda: workspace_ref.add_member(other_client.username,
                                                                                      WorkspaceMembership.ADMIN))
                self.assertRaises(UnauthorizedError, lambda: workspace_ref.change_membership(other_client.username,
                                                                                             WorkspaceMembership.ADMIN))

                workspace.change_membership(other_client.username, WorkspaceMembership.ADMIN)

                # Because the authorized user made other_client an ADMIN, these should now work
                workspace_ref.change_membership(other_client.username, WorkspaceMembership.ADMIN)  # no-op but OK

                # Still, should not be able to remove original OWNER
                self.assertRaises(RuntimeError, lambda: workspace_ref.change_membership(client.username,
                                                                                        WorkspaceMembership.ADMIN))

                # User should be able to downgrade themselves
                workspace_ref.change_membership(other_client.username, WorkspaceMembership.VIEWER)

                time.sleep(2)

                self.assertRaises(UnauthorizedError, lambda: workspace_ref.change_membership(other_client.username,
                                                                                             WorkspaceMembership.ADMIN))

    def test_membership_validation(self):
        for client, other_client in self.client_pairs:
            for workspace in client.workspaces:
                self.assertRaises(RuntimeError,
                                  lambda: workspace.add_member(other_client.username, "not-a-valid-membership"))
                self.assertEqual(len(workspace.get_members()), 1)
                self.assertIn(client.username, [m.username for m in workspace.get_members()])
                self.assertNotIn(other_client.username, [m.username for m in workspace.get_members()])


class TestSizeCalculation(GfTestCase):
    def test_size_read_only(self):
        """Tests that we cannot manually change the size of objects"""
        gf = make_gf()

        initial_workspace_size = gf.primary_workspace.size_bytes
        gf.primary_workspace.size_bytes = initial_workspace_size + 10
        gf.primary_workspace.save()

        gf.primary_workspace.fetch()
        self.assertEqual(gf.primary_workspace.size_bytes, initial_workspace_size)

        ana = gf.Analysis(name="test analysis", workspace=gf.primary_workspace).create()
        self.assertEqual(ana.size_bytes, 0)
        ana.size_bytes = 10
        ana.save()
        ana.fetch()
        self.assertEqual(ana.size_bytes, 0)

        fig = gf.Figure(name="test figure", analysis=ana, size_bytes=123).create()
        self.assertEqual(fig.size_bytes, 0)
        fig.size_bytes = 123
        fig.save()
        fig.fetch()
        self.assertEqual(fig.size_bytes, 0)

    def test_size(self):
        gf = make_gf()

        initial_workspace_size = gf.primary_workspace.size_bytes

        # Create a new analysis. Initial size should be 0
        ana = gf.Analysis(name="test analysis", workspace=gf.primary_workspace).create()
        self.assertEqual(ana.size_bytes, 0)
        ana.fetch()
        self.assertEqual(ana.size_bytes, 0)

        # Create a bunch of figures & revisions, each revision of arbitrary size 7
        num_figures = 3
        num_revisions = 4
        rev_size = 7
        for fig_idx in range(num_figures):
            fig = gf.Figure(name=f"figure {fig_idx}", analysis=ana).create()
            self.assertEqual(fig.size_bytes, 0)
            fig.fetch()
            self.assertEqual(fig.size_bytes, 0)

            for rev_idx in range(num_revisions):
                rev = gf.Revision(figure=fig, data=[gf.TextData(name="text", contents="1234567")]).create()
                self.assertEqual(rev.size_bytes, 7)
                fig.fetch()
                self.assertEqual(rev.size_bytes, 7)

        self.assertEqual(gf.primary_workspace.fetch().size_bytes,
                         initial_workspace_size + rev_size * num_figures * num_revisions)
        self.assertEqual(ana.fetch().size_bytes, rev_size * num_figures * num_revisions)

        deleted_revisions = 0
        deleted_figures = 0
        for fig in ana.figures[:-1]:
            fig.fetch()
            self.assertEqual(fig.size_bytes, rev_size * num_revisions)

            # Delete a revision
            fig.revisions[0].delete(delete=True)
            deleted_revisions += 1

            # Make sure changes propagated properly
            fig.fetch()
            self.assertEqual(fig.size_bytes, rev_size * (num_revisions - 1))

            ana.fetch()
            self.assertEqual(ana.size_bytes, rev_size * (num_figures - deleted_figures) * num_revisions - rev_size * deleted_revisions)

            gf.primary_workspace.fetch()
            self.assertEqual(gf.primary_workspace.size_bytes,
                             initial_workspace_size + rev_size * (num_figures - deleted_figures) * num_revisions - \
                             rev_size * deleted_revisions)

            # Delete the whole figure
            fig.delete(delete=True)
            deleted_figures += 1
            deleted_revisions = 0
            ana.fetch()
            self.assertEqual(ana.size_bytes, rev_size * (num_figures - deleted_figures) * num_revisions)

            gf.primary_workspace.fetch()
            self.assertEqual(gf.primary_workspace.size_bytes,
                             initial_workspace_size + rev_size * (num_figures - deleted_figures) * num_revisions)

        # At this point, we should have a single figure left, with all of its revisions intact
        ana.fetch()
        self.assertEqual(ana.size_bytes, rev_size * num_revisions)

        gf.primary_workspace.fetch()
        self.assertEqual(gf.primary_workspace.size_bytes, initial_workspace_size + rev_size * num_revisions)

        # Delete the analysis
        ana.delete(delete=True)
        gf.primary_workspace.fetch()
        self.assertEqual(gf.primary_workspace.size_bytes, initial_workspace_size)


class TestOrganizations(MultiUserTestCase):
    def test_creation(self):
        gf = make_gf()

        # No organizations at beginning
        self.assertListEqual(gf.organizations, [])

        my_org = gf.Organization(name="test org", description="").create()
        self.assertListEqual(gf.organizations, [my_org])
        self.assertEqual(my_org.name, "test org")
        self.assertEqual(my_org.description, "")

        self.assertListEqual(my_org.get_members(),
                             [MembershipInfo(gf.username, OrganizationMembership.ORG_ADMIN)])

        # Create a new workspace under this org
        worx = gf.Workspace(name="worx").create()
        worx.organization = my_org
        worx.save()

        # Workspace should now appear under this organization
        my_org.fetch()
        self.assertListEqual(list(my_org.workspaces), [worx])

        gf.primary_workspace.organization = my_org
        gf.primary_workspace.save()
        my_org.fetch()
        self.assertListEqual(list(my_org.workspaces), [worx, gf.primary_workspace])

        # Updates
        my_org.description = "test org description"
        my_org.save()

        self.assertEqual(my_org.fetch().description, "test org description")

    def test_member_management(self):
        for client, other_client in self.client_pairs:
            # Client creates an organization and a workspace under that org
            my_org = client.Organization(name="test org", description="").create()
            my_worx = client.Workspace(name="worx", organization=my_org).create()
            client.primary_workspace.organization = my_org
            client.primary_workspace.save()

            my_org.fetch()
            self.assertEqual(my_org.get_storage_info().vendor, "GoFigr.io")
            self.assertIsNone(my_org.get_storage_info().params)

            # Client should be able to set storage params
            my_org.set_storage_info("aws", {"bucket": "gofigr-flextest", "key": "data"})
            self.assertEqual(my_org.get_storage_info().vendor, "aws")
            self.assertEqual(my_org.get_storage_info().params, {"bucket": "gofigr-flextest", "key": "data"})

            # Other user should not be able to assign their workspaces to my org
            self.assertRaises(UnauthorizedError, other_client.Workspace(name="other worx", organization=my_org).create)

            self.assertListEqual(my_org.get_members(),
                                 [MembershipInfo(client.username, OrganizationMembership.ORG_ADMIN)])

            # Client 2 should be unable to access anything in the org
            my_org2 = self.clone_gf_object(my_org, other_client, bare=True)
            self.assertRaises(UnauthorizedError, my_org2.fetch)
            self.assertRaises(UnauthorizedError, my_org2.get_storage_info)
            self.assertRaises(UnauthorizedError, lambda: my_org2.set_storage_info("aws", {"bucket": "gofigr-flextest",
                                                                                          "key": "data"}))

            for obj in self.list_all_objects(client):
                self.assertRaises(UnauthorizedError, self.clone_gf_object(obj, other_client).fetch)

            # Add the other user as a creator
            my_org.add_member(other_client.username, OrganizationMembership.WORKSPACE_CREATOR)
            my_org2.fetch()  # this should now work

            # They should now have access to all objects in the org's workspaces
            for workspace in [my_worx, client.primary_workspace]:
                for obj in self.list_workspace_objects(workspace):
                    self.assertEqual(obj, self.clone_gf_object(obj, other_client).fetch())

            # But they still shouldn't have access to the other workspace
            non_org_workspaces = [w for w in client.workspaces if "test workspace" in w.name]
            self.assertEqual(len(non_org_workspaces), 1)
            non_org_worx = non_org_workspaces[0]

            # They shouldn't be able to upgrade their membership level
            self.assertRaises(UnauthorizedError,
                              lambda: self.clone_gf_object(my_org, other_client).change_membership(other_client.username,
                                                                                                   OrganizationMembership.ORG_ADMIN))

            for obj in self.list_workspace_objects(non_org_worx):
                self.assertRaises(UnauthorizedError, self.clone_gf_object(obj, other_client).fetch)

            # Other user should be able to create workspaces under our org
            worx2 = other_client.Workspace(name="other worx", organization=my_org).create()
            my_org.fetch()  # refresh list of workspaces

            self.assertEqual(worx2.fetch().organization.fetch().api_id, my_org.api_id)

            # Same for us under their workspace
            ana = client.Analysis(name="my analysis", organization=my_org, workspace=self.clone_gf_object(worx2, client)).create()
            self.assertEqual(ana.workspace.fetch().organization.fetch(), my_org)

            # We shouldn't be able to access anything in other user's non-org workspaces
            for worx in other_client.workspaces:
                if worx.api_id in [w.api_id for w in my_org.workspaces]:
                    continue

                for obj in self.list_workspace_objects(worx):
                    self.assertRaises(UnauthorizedError, lambda: self.clone_gf_object(obj, client).fetch())
                    self.assertRaises((UnauthorizedError, MethodNotAllowedError),
                                      lambda: self.clone_gf_object(obj, client).delete(delete=True))

            # Remove user from org
            my_org.remove_member(other_client.username)

            # Allow authorization cache to expire
            time.sleep(2.0)

            # They should no longer have access
            for workspace in [my_worx, client.primary_workspace]:
                for obj in self.list_workspace_objects(workspace):
                    self.assertRaises(UnauthorizedError, self.clone_gf_object(obj, other_client).fetch)

            # They should still have access to the workspace they themselves created.
            self.assertEqual(worx2.fetch().name, "other worx")


class TestFlexStorage(MultiUserTestCase):
    def _check_data(self, client, worx, prefix="s3://gofigr-flextest/", create=True):
        if create:
            self.create_test_analysis(client, worx)

        for data in self.list_data_objects(worx):
            info = data.get_storage_info()
            self.assertEqual(info['vendor'], "AWS")
            self.assertTrue(info['path'].startswith(prefix))

            self.assertGreater(data.size_bytes, 0)
            self.assertEqual(data.size_bytes, len(data.fetch().data))

    def test_flex_workspace(self):
        # By default, the vendor should be GoFigr
        for client in self.clients:
            for obj in self.list_data_objects(client.primary_workspace):
                self.assertEqual(obj.get_storage_info()['vendor'], "GoFigr.io")
                self.assertIsNone(obj.get_storage_info().get('path'))

            # Switch to flex storage
            worx = client.Workspace(name="worx").create()

            # Check the testing endpoint
            self.assertRaises(RuntimeError, lambda: worx.test_storage("aws", {"bucket": "gofigr-badbucket", "key": "data"}))
            self.assertEqual(worx.test_storage("aws", {"bucket": "gofigr-flextest", "key": "data"}).vendor, 'aws')
            self.assertEqual(worx.test_storage("aws", {"bucket": "gofigr-flextest2", "key": "data"}).vendor, 'aws')

            # The actual storage settings shouldn't have changed
            self.assertEqual(worx.get_storage_info().vendor, "GoFigr.io")

            # Switch storage
            self.assertRaises(RuntimeError, lambda: worx.set_storage_info("aws", {"bucket": "gofigr-badbucket", "key": "data"}))
            worx.set_storage_info("aws", {"bucket": "gofigr-flextest", "key": "data"})
            self.assertEqual(worx.get_storage_info().vendor, "aws")

            # Check
            self._check_data(client, worx)

    def test_flex_organizations(self):
        for client in self.clients:
            org = client.Organization(name="test org").create()
            worx = client.Workspace(name="org worx", organization=org).create()

            # Should fail because the org doesn't allow custom storage
            self.assertRaises(RuntimeError,
                              lambda: worx.set_storage_info("aws", {"bucket": "gofigr-flextest2", "key": "data"}))

            # Set flex storage through the organization
            org.set_storage_info("aws", {"bucket": "gofigr-flextest", "key": "data"})
            self.assertEqual(org.get_storage_info().vendor, "aws")
            self.assertEqual(worx.get_storage_info().vendor, "GoFigr.io")  # no flex at the workspace level
            self._check_data(client, worx, "s3://gofigr-flextest/")

            # Set to allow flex storage per workspace
            org.allow_per_workspace_storage_settings = True
            org.save()
            worx2 = client.Workspace(name="other worx", organization=org).create()
            worx2.set_storage_info("aws", {"bucket": "gofigr-flextest2", "key": "data"})
            self._check_data(client, worx2, "s3://gofigr-flextest2/")

            # New workspaces should still default to org's storage settings
            worx3 = client.Workspace(name="org worx 3", organization=org).create()
            self._check_data(client, worx3, "s3://gofigr-flextest/")

            # ... without impact on previously created workspaces
            self._check_data(client, worx2, "s3://gofigr-flextest2/", create=False)
            self._check_data(client, worx, "s3://gofigr-flextest/", create=False)


class TestAssets(GfTestCase):
    def setUp(self):
        self.gf = make_gf()
        self.initial_worx_size = self.gf.primary_workspace.fetch().size_bytes

        self.ds = self.gf.Asset(name="test dataset", workspace=self.gf.primary_workspace).create()
        self.ds2 = self.gf.Asset(name="test dataset 2", workspace=self.gf.primary_workspace).create()

        for dsi in [self.ds, self.ds2]:
            actual_ds = self.gf.Asset(api_id=dsi.api_id).fetch()
            self.assertEqual(dsi.name, actual_ds.name)
            self.assertEqual(dsi.workspace.api_id, actual_ds.workspace.api_id)

        self.reference_revs = [self.gf.AssetRevision(asset=self.ds,
                                             data=[
                                                 self.gf.Data(name="test.bin", data=bytes([idx, idx + 1, idx + 2, idx + 3]),
                                                         type=DataType.FILE)]).create()
                          for idx in range(5)]

    def test_find_hash(self):
        for rev in self.reference_revs:
            hits = self.gf.AssetRevision.find_by_hash(rev.data[0].calculate_hash())
            self.assertEqual(len(hits), 1)

            onehit = hits[0].fetch()
            self.assertEqual(onehit.api_id, rev.api_id)
            self.assertIsNotNone(onehit.api_id)
            self.assertEqual(onehit.data[0].calculate_hash(), rev.data[0].calculate_hash())
            self.assertIsNotNone(onehit.data[0].calculate_hash())

    def test_asset_creation(self):
        gf, ds, ds2, reference_revs = self.gf, self.ds, self.ds2, self.reference_revs

        for idx, rev in enumerate(reference_revs):
            rev2 = gf.AssetRevision(api_id=rev.api_id).fetch()
            self.assertEqual(rev.asset.api_id, rev2.asset.api_id)
            self.assertEqual(rev.data[0].data, rev2.data[0].data)

        actual_ds = gf.Asset(api_id=ds.api_id).fetch()
        actual_ds.fetch()  # fetch new revisions

        actual_ds2 = gf.Asset(api_id=ds2.api_id).fetch()
        actual_ds2.fetch()  # fetch new revisions

        for idx, rev in enumerate(reference_revs):
            rev2 = actual_ds.revisions[idx].fetch()
            self.assertEqual(rev.asset.api_id, rev2.asset.api_id)
            self.assertEqual(rev.data[0].data, rev2.data[0].data)
            self.assertEqual(rev2.data[0].data, bytes([idx, idx+1, idx+2, idx+3]))
            self.assertEqual(rev2.size_bytes, 4)

        self.assertEqual(actual_ds.size_bytes, 20)
        self.assertEqual(gf.primary_workspace.fetch().size_bytes, self.initial_worx_size + 20)

        # Delete a revision
        reference_revs[0].delete(delete=True)
        actual_ds.fetch()  # fetch new revisions
        actual_ds2.fetch()  # fetch new revisions
        self.assertEqual(len(actual_ds.revisions), 4)
        self.assertEqual(actual_ds.size_bytes, 16)
        self.assertEqual(len(actual_ds2.revisions), 0)
        self.assertEqual(actual_ds2.size_bytes, 0)
        self.assertEqual(gf.primary_workspace.fetch().size_bytes, self.initial_worx_size + 16)

        # Make sure the new dataset appears in recents
        recents = gf.primary_workspace.get_recents()
        self.assertIn(ds.api_id, [x.api_id for x in recents.assets])
        self.assertIn(ds2.api_id, [x.api_id for x in recents.assets])


class AssetTestCase(MultiUserTestCase):
    def setUp(self):
        super().setUp()
        for gf in self.clients:
            for worx in gf.workspaces:
                ds1 = gf.Asset(name="test dataset", workspace=worx).create()
                ds2 = gf.Asset(name="test dataset 2", workspace=worx).create()

                for dsi in [ds1, ds2]:
                    for idx in range(5):
                        gf.AssetRevision(asset=dsi,
                                         data=[
                                             gf.Data(name="test.bin",
                                                     data=bytes([idx, idx + 1, idx + 2, idx + 3]),
                                                     type=DataType.FILE)]).create()


class TestAssetPermissions(AssetTestCase):
    def test_asset_permissions(self):
        for client, other_client in self.client_pairs:
            for worx in client.workspaces:
                self.assertGreater(len(worx.assets), 0)

                for ds in worx.assets:
                    ds.fetch()  # should work fine
                    ds_other = self.clone_gf_object(ds, other_client)
                    self.assertRaises(UnauthorizedError, ds_other.fetch)

                    for rev in ds.revisions:
                        rev.fetch()  # should work fine
                        rev_other = self.clone_gf_object(rev, other_client)
                        self.assertRaises(UnauthorizedError, rev_other.fetch)


class TestFigureAssetAssociations(AssetTestCase):
    def test_asset_associations(self):
        for client, other_client in self.client_pairs:
            other_client.primary_workspace.fetch()
            other_ds1 = other_client.primary_workspace.assets[0].fetch()

            for worx in client.workspaces:
                worx.fetch()
                ds1 = worx.assets[0].fetch()
                ds2 = worx.assets[1].fetch()

                for ana in worx.analyses:
                    ana.fetch()
                    for fig in ana.figures:
                        fig.fetch()
                        for rev in fig.revisions:
                            rev.assets = [client.AssetLinkedToFigure(figure_revision=rev,
                                                                     asset_revision=ds1.revisions[0],
                                                                     use_type="direct"),
                                          client.AssetLinkedToFigure(figure_revision=rev,
                                                                     asset_revision=ds2.revisions[1],
                                                                     use_type="indirect")]
                            rev.save()

                            server_rev = client.Revision(api_id=rev.api_id).fetch()
                            self.assertEqual(len(server_rev.assets), 2)
                            self.assertEqual(server_rev.assets[0].use_type, "direct")
                            self.assertEqual(server_rev.assets[0].figure_revision.api_id, rev.api_id)
                            self.assertEqual(server_rev.assets[0].asset_revision.api_id, ds1.revisions[0].api_id)

                            self.assertEqual(server_rev.assets[1].use_type, "indirect")
                            self.assertEqual(server_rev.assets[1].figure_revision.api_id, rev.api_id)
                            self.assertEqual(server_rev.assets[1].asset_revision.api_id, ds2.revisions[1].api_id)

                            # The assets should now include backlinks to the figures
                            for dsx in [ds1, ds2]:
                                for drev in dsx.revisions:
                                    drev.fetch()

                            self.assertEqual(len(ds1.revisions[0].figure_revisions), 1)
                            self.assertEqual(ds1.revisions[0].figure_revisions[0].figure_revision.api_id, rev.api_id)
                            self.assertEqual(len(ds1.revisions[1].figure_revisions), 0)

                            self.assertEqual(len(ds2.revisions[1].figure_revisions), 1)
                            self.assertEqual(ds2.revisions[1].figure_revisions[0].figure_revision.api_id, rev.api_id)
                            self.assertEqual(len(ds2.revisions[0].figure_revisions), 0)

                            # Now create new associations and make sure they completely overwrite the old ones
                            rev.assets = [client.AssetLinkedToFigure(figure_revision=rev,
                                                                     asset_revision=ds1.revisions[1],
                                                                     use_type="direct"),
                                          client.AssetLinkedToFigure(figure_revision=rev,
                                                                     asset_revision=ds2.revisions[0],
                                                                     use_type="indirect")]
                            rev.save()

                            server_rev = client.Revision(api_id=rev.api_id).fetch()
                            for dsx in [ds1, ds2]:
                                for drev in dsx.revisions:
                                    drev.fetch()

                            self.assertEqual(len(server_rev.assets), 2)
                            self.assertEqual(server_rev.assets[0].use_type, "direct")
                            self.assertEqual(server_rev.assets[0].figure_revision.api_id, rev.api_id)
                            self.assertEqual(server_rev.assets[0].asset_revision.api_id, ds1.revisions[1].api_id)

                            self.assertEqual(server_rev.assets[1].use_type, "indirect")
                            self.assertEqual(server_rev.assets[1].figure_revision.api_id, rev.api_id)
                            self.assertEqual(server_rev.assets[1].asset_revision.api_id, ds2.revisions[0].api_id)

                            self.assertEqual(len(ds1.revisions[1].figure_revisions), 1)
                            self.assertEqual(ds1.revisions[1].figure_revisions[0].figure_revision.api_id, rev.api_id)
                            self.assertEqual(len(ds1.revisions[0].figure_revisions), 0)

                            self.assertEqual(len(ds2.revisions[0].figure_revisions), 1)
                            self.assertEqual(ds2.revisions[0].figure_revisions[0].figure_revision.api_id, rev.api_id)
                            self.assertEqual(len(ds2.revisions[1].figure_revisions), 0)

                            # Test permissions
                            rev.assets = [client.AssetLinkedToFigure(figure_revision=rev,
                                                                     asset_revision=other_ds1.revisions[1],
                                                                     use_type="direct"),
                                          client.AssetLinkedToFigure(figure_revision=rev,
                                                                     asset_revision=ds2.revisions[0],
                                                                     use_type="indirect")]
                            self.assertRaises(UnauthorizedError, rev.save)

                            # Clear associations
                            rev.assets = []
                            rev.save()
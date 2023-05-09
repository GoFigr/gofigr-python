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

from gofigr import GoFigr, CodeLanguage, WorkspaceType, UnauthorizedError, ShareableModelMixin, WorkspaceMembership


def make_gf(authenticate=True, username=None, password=None):
    return GoFigr(username=username or os.environ['GF_TEST_USER'],
                  password=password or os.environ['GF_TEST_PASSWORD'],
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


class TestUsers(TestCase):
    def test_user_info(self):
        gf = make_gf()
        info = gf.user_info()
        self.assertEqual(gf.user_info(), gf.user_info(gf.username))
        self.assertEqual(info.username, gf.username)
        self.assertEqual(info.email, 'testuser@server.com')

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

        # We should not be able to change info for anyone else
        for other_user in ['testuser2']:
            info.username = other_user
            self.assertRaises(UnauthorizedError, lambda: gf.update_user_info(info))

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
            self.assertEqual(ana.workspace, workspace)

        analysis2.name = "another name"
        analysis2.description = "another description"
        analysis2.save()
        analysis.fetch()  # refresh

        for ana in [analysis, analysis2]:
            self.assertEqual(ana.name, "another name")
            self.assertEqual(ana.description, "another description")
            self.assertEqual(ana.workspace, workspace)

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
        self.assertEqual(analysis.workspace, gf.primary_workspace)

    def test_lazy_loading(self):
        gf = make_gf()
        workspace = gf.primary_workspace

        analysis = gf.Analysis(name="test", description="test", workspace=workspace)
        analysis.create()

        # Since no data is actually loaded until needed, this should work despite the ID being bad
        bad_lazy_analysis = gf.Analysis(analysis.api_id + "bad", lazy=True)

        # ... but this should now fail
        self.assertRaises(RuntimeError, lambda: bad_lazy_analysis.name)

        # This should work just fine
        lazy_analysis = gf.Analysis(analysis.api_id, lazy=True)
        self.assertEqual(lazy_analysis.api_id, analysis.api_id)
        self.assertEqual(lazy_analysis.name, analysis.name)
        self.assertEqual(lazy_analysis.description, analysis.description)
        self.assertEqual(lazy_analysis.workspace, analysis.workspace)

        # Values assigned to lazy properties should not be overridden
        # when the data is fetched
        lazy_analysis2 = gf.Analysis(analysis.api_id, lazy=True)
        lazy_analysis2.name = "new name"
        self.assertEqual(lazy_analysis2.api_id, analysis.api_id)
        self.assertEqual(lazy_analysis2.name, "new name")
        self.assertEqual(lazy_analysis2.description, analysis.description)
        self.assertEqual(lazy_analysis2.workspace, analysis.workspace)


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
        return self.load_image_data(nonce) + self.load_table_data(nonce) + self.load_code_data(nonce)


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
                self.assertEqual(rev, server_rev)
                self.assertEqual(server_rev.metadata, {'index': idx})
                self.assertEqual(server_rev.figure, fig)
                self.assertEqual(server_rev.figure.analysis, ana)

                # Validate image data
                for data_getter, expected_length, fields_to_check in \
                    [(lambda r: r.image_data, 3, ["name", "data", "is_watermarked", "format"]),
                     (lambda r: r.code_data, 2, ["name", "data", "language", "contents"]),
                     (lambda r: r.table_data, 2, ["name", "data", "format", "dataframe"])]:
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

            _test_timestamps(self, gf, rev, 'metadata', ['a', 'b', 'c'])

            revisions.append(rev)

        fig.fetch()
        self.assertEqual(len(fig.revisions), 5)

        # Delete revisions
        for rev in fig.revisions:
            rev.delete(delete=True)

        # Delete the analysis
        ana.delete(delete=True)


class MultiUserTestCase(TestCase):
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
                ana = workspace.analyses.create(gf.Analysis(name=f"{gf.username}'s test analysis"))
                fig = ana.figures.create(gf.Figure(name=f"{gf.username}'s test figure"))

                for idx in range(5):
                    rev = gf.Revision(metadata={'index': idx},
                                      data=TestData(gf).load_external_data(nonce=idx))
                    fig.revisions.create(rev)

    def tearDown(self):
        return self.clean_up()

    def clean_up(self):
        for gf in self.clients:
            for w in gf.workspaces:
                w.fetch()  # Refresh
                if w.workspace_type != WorkspaceType.PRIMARY:
                    w.delete(delete=True)
                else:
                    for ana in w.analyses:
                        ana.delete(delete=True)

                    for member in w.get_members():
                        if member.membership_type != "owner":
                            w.remove_member(member.username)

    def get_gf_type(self, obj, client):
        return getattr(client, type(obj)._gofigr_type_name)

    def list_all_objects(self, gf):
        for workspace in gf.workspaces:
            yield workspace

            for analysis in workspace.analyses:
                yield analysis

                for fig in analysis.figures:
                    yield fig

                    for rev in fig.revisions:
                        yield rev

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

                # DELETE
                with self.assertRaises(UnauthorizedError, msg=f"Unauthorized delete granted to {own_obj}"):
                    not_own_obj.delete(delete=True)

                # UPDATE
                if hasattr(own_obj, 'name'):
                    not_own_obj.name = "gotcha"
                elif hasattr(own_obj, 'metadata'):
                    not_own_obj.metadata = {'gotcha': 'oops'}
                else:
                    raise ValueError(f"Don't know how to update {not_own_obj}")

                for patch in [False, True]:
                    with self.assertRaises(UnauthorizedError, msg=f"Unauthorized update granted on {own_obj}"):
                        not_own_obj.save(patch=patch)

                # Make sure the properties didn't actually change
                own_obj2 = self.clone_gf_object(own_obj, client, bare=True).fetch()
                self.assertEqual(str(own_obj.to_json()), str(own_obj2.to_json()))


class TestPermissions(MultiUserTestCase):
    def test_exclusivity(self):
        return self.assert_exclusivity()

    def test_malicious_move(self):
        for client, other_client in self.client_pairs:
            # Case 1: user moving their analyses (to which they have access) to another users' workspace (to which
            # they do not have access)
            for w in client.workspaces:
                for ana in w.analyses:
                    ana.workspace = other_client.primary_workspace

                    for patch in [False, True]:
                        with self.assertRaises(UnauthorizedError,
                                               msg=f"Unauthorized move granted on: {ana} -> {ana.workspace}"):
                            ana.save(patch=patch)


                    # Likewise with figures
                    for fig in ana.figures:
                        fig.analysis = other_client.primary_workspace.analyses[0]

                        for patch in [False, True]:
                            with self.assertRaises(UnauthorizedError,
                                                   msg=f"Unauthorized move granted on: {fig} -> {fig.analysis}"):
                                fig.save(patch=patch)

            # Case 2: user moving others' analyses (to which they don't have access) into their own workspace
            # (to which they do)
            for w in other_client.workspaces:
                for ana in w.analyses:
                    ana.workspace = client.primary_workspace

                    for patch in [False, True]:
                        with self.assertRaises(UnauthorizedError,
                                               msg=f"Unauthorized move granted on: {ana} -> {ana.workspace}"):
                            ana.save(patch=patch)

                    # Same with figures
                    for fig in ana.figures:
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

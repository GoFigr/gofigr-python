"""\
Copyright (c) 2023, Flagstaff Solutions, LLC
All rights reserved.

"""
from collections import Counter
from unittest import TestCase

from gofigr import WorkspaceType
from tests.test_client import make_gf


def get_action_counts(logs):
    return tuple(sorted(Counter([log.action for log in logs]).items()))


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

    def test_logs(self):
        gf = make_gf()

        workspace = gf.Workspace(name="Test workspace").create()
        ana = gf.Analysis(name="Test analysis", workspace=workspace).create()
        fig = gf.Figure(name="Test figure", analysis=ana).create()
        rev = gf.Revision(figure=fig, metadata={'test': 1}).create()

        # Update workspace name
        workspace.name = "Updated name"
        workspace.save()

        # Update figure name
        fig.name = "Updated name"
        fig.save()

        # Update revision metadata
        rev.metadata = {'test': 2}
        rev.save()

        # Delete revision
        rev.delete(delete=True)

        # Grab the workspace logs
        logs = [log.fetch() for log in workspace.get_logs()]
        self.assertEqual(len(logs), 8)  # 4 create + 3 update + 1 delete
        self.assertEqual(get_action_counts(logs), (("create", 4), ("delete", 1), ("update", 3)))

        # Grab the analysis logs. Should be the same except the workspace-level actions.
        ana_logs = [log.fetch() for log in ana.get_logs()]
        self.assertEqual(len(ana_logs), 6)  # 4 create + 3 update + 1 delete
        self.assertEqual(get_action_counts(ana_logs), (("create", 3), ("delete", 1), ("update", 2)))

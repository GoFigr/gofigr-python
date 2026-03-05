"""\
Copyright (c) 2023, Flagstaff Solutions, LLC
All rights reserved.

Smoke test for invitations - detailed tests are on the server.
"""
import unittest

from gofigr.models import WorkspaceMembership

from tests.test_client import MultiUserTestCaseBase


class TestInvitationsSmokeTest(MultiUserTestCaseBase, unittest.TestCase):
    """Smoke test for invitations - detailed tests are on the server."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.n_revisions = 0

    def test_basic_workspace_invitation(self):
        """Verify basic invitation create/delete works."""
        gf = self.gf1
        workspace = gf.primary_workspace

        # Create invitation
        invite = gf.WorkspaceInvitation(
            email="test@example.com",
            workspace=workspace,
            membership_type=WorkspaceMembership.CREATOR
        )
        invite.create()

        # Token should be returned at creation
        self.assertIsNotNone(invite.token)
        self.assertIsNotNone(invite.api_id)

        # Should appear in workspace invitations
        invites = workspace.get_invitations()
        invite_ids = [inv.api_id for inv in invites]
        self.assertIn(invite.api_id, invite_ids)

        # Delete invitation
        invite.delete()

        # Should be gone
        invites = workspace.get_invitations()
        invite_ids = [inv.api_id for inv in invites]
        self.assertNotIn(invite.api_id, invite_ids)

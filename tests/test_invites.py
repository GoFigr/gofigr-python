"""\
Copyright (c) 2023, Flagstaff Solutions, LLC
All rights reserved.

"""
import time
from datetime import datetime, timedelta

import numpy as np

from gofigr import UnauthorizedError
from gofigr.models import WorkspaceMembership

from tests.test_client import GfTestCase, MultiUserTestCase


def has_invite(workspace, invite):
    for inv in workspace.get_invitations():
        if inv.api_id == invite.api_id:
            return True
    return False

class TestInvitations(MultiUserTestCase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.n_revisions = 0

    def test_creation_and_deletion(self):
        gf = self.gf1
        invite = gf.WorkspaceInvitation(email="testuser@flagstaff.ai",
                                        workspace=gf.primary_workspace,
                                        membership_type=WorkspaceMembership.CREATOR)
        invite.create()
        self.assertIsNotNone(invite.token)

        all_invites = gf.primary_workspace.get_invitations()
        for inv in all_invites:
            self.assertIsNone(inv.token)  # should only be provided at creation

        self.assertIsNone(gf.WorkspaceInvitation(api_id=invite.api_id).fetch().token)
        self.assertIsNotNone(gf.WorkspaceInvitation(api_id=invite.api_id).fetch().email)

        self.assertTrue(has_invite(gf.primary_workspace, invite), msg="Created invite not found")

        workspace2 = gf.Workspace(name="Second workspace").create()
        invite2 = gf.WorkspaceInvitation(email="testuser@flagstaff.ai",
                                         workspace=workspace2,
                                         membership_type=WorkspaceMembership.ADMIN)
        invite2.create()
        self.assertIsNotNone(invite2.token)
        self.assertNotEqual(invite.token, invite2.token)

        # Invites should be exclusive to workspaces
        self.assertTrue(has_invite(gf.primary_workspace, invite))
        self.assertFalse(has_invite(workspace2, invite))

        self.assertFalse(has_invite(gf.primary_workspace, invite2))
        self.assertTrue(has_invite(workspace2, invite2))

        # Delete both invites
        invite.delete()
        invite2.delete()
        self.assertFalse(has_invite(gf.primary_workspace, invite))
        self.assertFalse(has_invite(workspace2, invite))

        self.assertFalse(has_invite(gf.primary_workspace, invite2))
        self.assertFalse(has_invite(workspace2, invite2))

    def test_self_acceptance(self):
        invite1 = self.gf1.WorkspaceInvitation(email="testuser@flagstaff.ai",
                                               workspace=self.gf1.primary_workspace,
                                               membership_type=WorkspaceMembership.CREATOR)
        invite1.create()

        # This should fail, because we're already a member
        self.assertRaises(RuntimeError, lambda: invite1.accept())

        # Invitations can only be tried once. This one should no longer exist.
        self.assertRaises(RuntimeError, lambda: invite1.fetch())

    def test_acceptance(self):
        invite = self.gf1.WorkspaceInvitation(email="testuser@flagstaff.ai",
                                              workspace=self.gf1.primary_workspace,
                                              membership_type=WorkspaceMembership.CREATOR)
        token = invite.create().token

        # Verify that User 2 doesn't have access yet
        self.assertRaises(RuntimeError, lambda: self.gf2.Workspace(api_id=self.gf1.primary_workspace.api_id).fetch())

        # User 2 accepts the invite
        invite_u2 = self.gf2.WorkspaceInvitation(token=token)
        invite_u2.accept()

        # User 2 should now be listed as a member
        member, = [m for m in self.gf1.primary_workspace.get_members() if m.username == self.gf2.username]
        self.assertEqual(member.username, self.gf2.username)
        self.assertEqual(member.membership_type, WorkspaceMembership.CREATOR)

        # User 2 should have access to the workspace
        w = self.gf2.Workspace(api_id=self.gf1.primary_workspace.api_id).fetch()
        self.assertEqual(w.name, self.gf1.primary_workspace.name)

        # The invite should no longer exist
        self.assertRaises(RuntimeError, lambda: invite_u2.fetch())

    def test_expiration(self):
        invite = self.gf1.WorkspaceInvitation(email="testuser@flagstaff.ai",
                                              workspace=self.gf1.primary_workspace,
                                              expiry=datetime.now() + timedelta(seconds=1),
                                              membership_type=WorkspaceMembership.CREATOR)
        token = invite.create().token

        # Wait for invitation to expire
        time.sleep(2)

        # User 2 tries to accept the invite. It should raise an exception.
        invite_u2 = self.gf2.WorkspaceInvitation(token=token)
        self.assertRaises(RuntimeError, lambda: invite_u2.accept())

    def test_malicious_invites(self):
        # User 1 invites themselves to User 2's workspace
        invite = self.gf1.WorkspaceInvitation(email="testuser@flagstaff.ai",
                                              workspace=self.gf2.primary_workspace,
                                              expiry=datetime.now() + timedelta(seconds=1),
                                              membership_type=WorkspaceMembership.CREATOR)
        self.assertRaises(UnauthorizedError, lambda: invite.create())

        # User 2 tries to obtain and delete a valid invite created by User 1 without a token
        invite = self.gf1.WorkspaceInvitation(email="testuser@flagstaff.ai",
                                              workspace=self.gf1.primary_workspace,
                                              expiry=datetime.now() + timedelta(seconds=1),
                                              membership_type=WorkspaceMembership.CREATOR)
        invite.create()

        invite2 = self.gf2.WorkspaceInvitation(api_id=invite.api_id)
        self.assertRaises(UnauthorizedError, lambda: invite2.fetch())
        self.assertRaises(UnauthorizedError, lambda: invite2.delete())

    def test_token_uniqueness(self):
        """This is a simple sanity check that tokens are random"""
        invite = self.gf1.WorkspaceInvitation(email="testuser@flagstaff.ai",
                                              workspace=self.gf1.primary_workspace,
                                              membership_type=WorkspaceMembership.CREATOR)
        token = invite.create().token

        # Verbatim token should work
        invite2 = self.gf1.WorkspaceInvitation(token=token).fetch()

        # Minor variations should not
        for _ in range(100):
            token_variation = list(token)
            rand_idx = np.random.choice(np.arange(len(token)))
            token_variation[rand_idx] = np.random.choice(list(set(token) - {token[rand_idx]}))
            self.assertRaises(RuntimeError,
                              lambda: self.gf1.WorkspaceInvitation(token="".join(token_variation)).fetch())

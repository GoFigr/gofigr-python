"""\
Copyright (c) 2023, Flagstaff Solutions, LLC
All rights reserved.

"""
import time
import unittest
from datetime import datetime, timedelta

import numpy as np

from gofigr import UnauthorizedError
from gofigr.models import WorkspaceMembership, OrganizationMembership

from tests.test_client import MultiUserTestCaseBase


def has_invite(target, invite):
    for inv in target.get_invitations():
        if inv.api_id == invite.api_id:
            return True
    return False


class TestInvitationsBase(MultiUserTestCaseBase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.n_revisions = 0

    def make_creator_invite(self, gf, target, expiry=None):
        raise NotImplementedError()

    def make_admin_invite(self, gf, target, expiry=None):
        raise NotImplementedError()

    def get_target_class(self, gf):
        raise NotImplementedError()

    def get_invite_class(self, gf):
        raise NotImplementedError()

    def get_primary_target(self, gf):
        raise NotImplementedError()

    def get_secondary_target(self, gf):
        raise NotImplementedError()

    def test_creation_and_deletion(self):
        gf = self.gf1
        target = self.get_primary_target(gf)

        invite = self.make_creator_invite(gf, target)
        invite.create()
        self.assertIsNotNone(invite.token)

        all_invites = target.get_invitations()
        for inv in all_invites:
            self.assertIsNone(inv.token)  # should only be provided at creation

        self.assertIsNone(self.get_invite_class(gf)(api_id=invite.api_id).fetch().token)
        self.assertIsNotNone(self.get_invite_class(gf)(api_id=invite.api_id).fetch().email)

        self.assertTrue(has_invite(target, invite), msg="Created invite not found")

        target2 = self.get_secondary_target(gf)
        invite2 = self.make_admin_invite(gf, target2)
        invite2.create()
        self.assertIsNotNone(invite2.token)
        self.assertNotEqual(invite.token, invite2.token)

        # Invites should be exclusive to workspaces
        self.assertTrue(has_invite(target, invite))
        self.assertFalse(has_invite(target2, invite))

        self.assertFalse(has_invite(target, invite2))
        self.assertTrue(has_invite(target2, invite2))

        # Delete both invites
        invite.delete()
        invite2.delete()
        self.assertFalse(has_invite(target, invite))
        self.assertFalse(has_invite(target2, invite))

        self.assertFalse(has_invite(target, invite2))
        self.assertFalse(has_invite(target2, invite2))

    def test_self_acceptance(self):
        invite1 = self.make_creator_invite(self.gf1, self.get_primary_target(self.gf1))
        invite1.create()

        # This should fail, because we're already a member
        self.assertRaises(RuntimeError, lambda: invite1.accept())

        # Invitations can only be tried once. This one should no longer exist.
        self.assertRaises(RuntimeError, lambda: invite1.fetch())

    def test_acceptance(self):
        target = self.get_primary_target(self.gf1)
        invite = self.make_creator_invite(self.gf1, target)
        token = invite.create().token

        # Verify that User 2 doesn't have access yet
        self.assertRaises(RuntimeError, lambda: self.get_target_class(self.gf2)(api_id=target.api_id).fetch())

        # User 2 accepts the invite
        invite_u2 = self.get_invite_class(self.gf2)(token=token)
        invite_u2.accept()

        # User 2 should now be listed as a member
        member, = [m for m in target.get_members() if m.username == self.gf2.username]
        self.assertEqual(member.username, self.gf2.username)
        self.assertEqual(member.membership_type, invite.membership_type)

        # User 2 should have access to the workspace
        w = self.get_target_class(self.gf2)(api_id=target.api_id).fetch()
        self.assertEqual(w.name, target.name)

        # The invite should no longer exist
        self.assertRaises(RuntimeError, lambda: invite_u2.fetch())

    def test_expiration(self):
        target = self.get_primary_target(self.gf1)
        invite = self.make_creator_invite(self.gf1, target, expiry=datetime.now() + timedelta(seconds=1))
        token = invite.create().token

        # Wait for invitation to expire
        time.sleep(2)

        # User 2 tries to accept the invite. It should raise an exception.
        invite_u2 = self.get_invite_class(self.gf2)(token=token)
        self.assertRaises(RuntimeError, lambda: invite_u2.accept())

    def test_malicious_invites(self):
        # User 1 invites themselves to User 2's workspace
        target1 = self.get_primary_target(self.gf1)
        target2 = self.get_primary_target(self.gf2)

        invite = self.make_creator_invite(self.gf1, target2, expiry=datetime.now() + timedelta(seconds=1))
        self.assertRaises(UnauthorizedError, lambda: invite.create())

        # User 2 tries to obtain and delete a valid invite created by User 1 without a token
        invite = self.make_creator_invite(self.gf1, target1, expiry=datetime.now() + timedelta(seconds=1))
        invite.create()

        invite2 = self.get_invite_class(self.gf2)(api_id=invite.api_id)
        self.assertRaises(UnauthorizedError, lambda: invite2.fetch())
        self.assertRaises(UnauthorizedError, lambda: invite2.delete())

    def test_token_uniqueness(self):
        """This is a simple sanity check that tokens are random"""
        invite = self.make_creator_invite(self.gf1, self.get_primary_target(self.gf1))
        token = invite.create().token

        # Verbatim token should work
        invite2 = self.get_invite_class(self.gf1)(token=token).fetch()

        # Minor variations should not
        for _ in range(100):
            token_variation = list(token)
            rand_idx = np.random.choice(np.arange(len(token)))
            token_variation[rand_idx] = np.random.choice(list(set(token) - {token[rand_idx]}))
            self.assertRaises(RuntimeError,
                              lambda: self.get_invite_class(self.gf1)(token="".join(token_variation)).fetch())


class TestWorkspaceInvitations(TestInvitationsBase, unittest.TestCase):
    def make_creator_invite(self, gf, target, expiry=None):
        return gf.WorkspaceInvitation(email="testuser@flagstaff.ai",
                                      workspace=target,
                                      expiry=expiry,
                                      membership_type=WorkspaceMembership.CREATOR)

    def make_admin_invite(self, gf, target, expiry=None):
        return gf.WorkspaceInvitation(email="testuser@flagstaff.ai",
                                      workspace=target,
                                      expiry=expiry,
                                      membership_type=WorkspaceMembership.ADMIN)

    def get_target_class(self, gf):
        return gf.Workspace

    def get_invite_class(self, gf):
        return gf.WorkspaceInvitation

    def get_primary_target(self, gf):
        return gf.primary_workspace

    def get_secondary_target(self, gf):
        return gf.Workspace(name="Second workspace").create()


class TestOrganizationInvitations(TestInvitationsBase, unittest.TestCase):
    def make_creator_invite(self, gf, target, expiry=None):
        return gf.OrganizationInvitation(email="testuser@flagstaff.ai",
                                         organization=target,
                                         expiry=expiry,
                                         membership_type=OrganizationMembership.WORKSPACE_CREATOR)

    def make_admin_invite(self, gf, target, expiry=None):
        return gf.OrganizationInvitation(email="testuser@flagstaff.ai",
                                         organization=target,
                                         expiry=expiry,
                                         membership_type=OrganizationMembership.ORG_ADMIN)

    def get_target_class(self, gf):
        return gf.Organization

    def get_invite_class(self, gf):
        return gf.OrganizationInvitation

    def get_primary_target(self, gf):
        return gf.Organization(name="Org 1").create()

    def get_secondary_target(self, gf):
        return gf.Organization(name="Org 2").create()

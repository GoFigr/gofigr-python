"""\
Copyright (c) 2023, Flagstaff Solutions, LLC
All rights reserved.

"""
import time
from datetime import datetime, timedelta

from dateutil.tz import tz

from gofigr import UnauthorizedError, GoFigr

from tests.test_client import MultiUserTestCase


def has_invite(workspace, invite):
    for inv in workspace.get_invitations():
        if inv.api_id == invite.api_id:
            return True
    return False


class TestMetadataProxy(MultiUserTestCase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.n_revisions = 0

    def test_proxy(self):
        gf = self.gf1

        # First make sure we can't create proxies which don't expire or expire too far into the future
        meta = gf.MetadataProxy(expiry=None).create()
        self.assertIsNotNone(meta.expiry)
        self.assertLess((meta.expiry - meta.created).total_seconds(), 24 * 3600)

        meta = gf.MetadataProxy(expiry=datetime.now() + timedelta(days=7)).create()
        self.assertIsNotNone(meta.expiry)
        self.assertLess((meta.expiry - meta.created).total_seconds(), 24 * 3600)

        meta = gf.MetadataProxy(expiry=datetime.now(tz=tz.tzlocal()) + timedelta(seconds=4)).create()

        meta2 = gf.MetadataProxy(token=meta.token).fetch()
        for prop in ['token', 'api_id', 'initiator']:
            self.assertIsNotNone(getattr(meta, prop))
            self.assertIsNotNone(getattr(meta2, prop))
            self.assertEqual(getattr(meta, prop), getattr(meta2, prop))

        self.assertIsNone(meta.updated)
        self.assertIsNone(meta2.updated)

        meta.metadata = {"abc": "xyz"}
        meta.save()

        meta2.fetch()
        self.assertEqual(meta.metadata, {"abc": "xyz"})
        self.assertEqual(meta.metadata, meta2.metadata)

        self.assertIsNotNone(meta.updated)
        self.assertIsNotNone(meta2.updated)
        self.assertEqual(meta.updated, meta2.updated)
        self.assertLess((datetime.now(tz=tz.tzlocal()) - meta.updated).total_seconds(), 10)

        # User 2 should not be able to fetch any of the metadata, even with a valid token
        u2_meta = self.gf2.MetadataProxy(token=meta.token)
        self.assertRaises(UnauthorizedError, lambda: u2_meta.fetch())

        # However, they should be able to update the metadata
        u2_meta.metadata = "123"
        u2_meta.save()

        meta.fetch()
        self.assertEqual(meta.metadata, "123")

        # Likewise for anonymous access
        gfanon = GoFigr(anonymous=True, url=self.gf1.service_url)
        anon_meta = gfanon.MetadataProxy(token=meta.token)
        self.assertRaises(UnauthorizedError, lambda: anon_meta.fetch())

        anon_meta.metadata = "456"
        anon_meta.save()

        meta.fetch()
        self.assertEqual(meta.metadata, "456")

        # Wait for the token to expire
        time_wait = (meta.expiry - meta.created).total_seconds()
        print(f"Waiting {time_wait:.1f}s for token to expire")
        time.sleep(time_wait)

        self.assertRaises(RuntimeError, lambda: meta.fetch())
        self.assertRaises(RuntimeError, lambda: meta.save())

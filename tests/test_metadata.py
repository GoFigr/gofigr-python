"""\
Copyright (c) 2023, Flagstaff Solutions, LLC
All rights reserved.

Smoke test for metadata proxy - detailed tests are on the server.
"""

from tests.test_client import MultiUserTestCase


class TestMetadataProxySmokeTest(MultiUserTestCase):
    """Smoke test for metadata proxy - detailed tests are on the server."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.n_revisions = 0

    def test_basic_metadata_proxy(self):
        """Verify basic metadata proxy create/update/fetch works."""
        gf = self.gf1

        # Create proxy
        meta = gf.MetadataProxy().create()
        self.assertIsNotNone(meta.token)
        self.assertIsNotNone(meta.api_id)

        # Fetch by token
        meta2 = gf.MetadataProxy(token=meta.token).fetch()
        self.assertEqual(meta.api_id, meta2.api_id)

        # Update metadata
        meta.metadata = {"test": "value"}
        meta.save()

        # Verify update
        meta2.fetch()
        self.assertEqual(meta2.metadata, {"test": "value"})

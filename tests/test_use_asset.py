"""\
Unit tests for gofigr.jupyter.use_asset (no server: a fake client).

Copyright (c) 2026, Flagstaff Solutions, LLC
All rights reserved.
"""
import os
from types import SimpleNamespace

import pytest
from blake3 import blake3

from gofigr import jupyter as gfj


class FakeData:
    def __init__(self, payload, name):
        self.payload = payload
        self.name = name
        self.hash = blake3(payload).hexdigest()
        self.data = None
        self.fetches = 0

    @property
    def is_shallow(self):
        return self.data is None

    def fetch(self):
        self.fetches += 1
        self.data = self.payload

    def write(self, path):
        with open(path, 'wb') as f:
            f.write(self.data)


class FakeRevision:
    def __init__(self, api_id, payload, name):
        self.api_id = api_id
        self.app_url = f"https://app/asset_revision/{api_id}"
        self.asset = SimpleNamespace(name="clinical", api_id="A1", fetch=lambda: None)
        self._payload = payload
        self._name = name
        self.data = None

    def fetch(self, fetch_data=True):
        if self.data is None:
            self.data = [FakeData(self._payload, self._name)]
        return self


class FakeSync:
    def __init__(self):
        self.registered = []

    def register(self, rev):
        self.registered.append(rev)
        return rev


class FakeGf:
    def __init__(self, rev):
        self._rev = rev
        self.sync = FakeSync()
        fake = self

        class AssetRevision:  # pylint: disable=too-few-public-methods
            def __init__(self, api_id=None):
                self.api_id = api_id

            def fetch(self, fetch_data=True):
                return fake._rev.fetch(fetch_data=fetch_data)
        self.AssetRevision = AssetRevision


@pytest.fixture
def fake(monkeypatch):
    rev = FakeRevision("R1", b"a,b\n1,2\n", "clinical.csv")
    gf = FakeGf(rev)
    monkeypatch.setattr(gfj, "get_gofigr", lambda: gf)
    monkeypatch.setattr(gfj, "AssetWidget", lambda rev: SimpleNamespace(show=lambda: None))
    # require_configured is applied at import time: satisfy it by patching the extension lookup it calls.
    ext = SimpleNamespace(gf=gf, is_ready=True, check_config=lambda: None)
    monkeypatch.setattr(gfj, "_get_extension_nocheck", lambda: ext)
    return gf, rev


def test_use_asset_downloads_verifies_and_registers(tmp_path, fake):
    gf, rev = fake
    path = gfj.use_asset("R1", directory=str(tmp_path / "data"), quiet=True)
    assert path == os.path.join(str(tmp_path / "data"), "clinical.csv")
    assert open(path, 'rb').read() == b"a,b\n1,2\n"
    assert gf.sync.registered == [rev]
    assert rev.data[0].fetches == 1


def test_use_asset_reuses_a_matching_local_file(tmp_path, fake):
    gf, rev = fake
    target = tmp_path / "clinical.csv"
    target.write_bytes(b"a,b\n1,2\n")
    gfj.use_asset("R1", path=str(target), quiet=True)
    assert rev.data[0].fetches == 0          # digest matched: no download
    assert gf.sync.registered == [rev]       # still registered as an input


def test_use_asset_overwrites_a_stale_local_file(tmp_path, fake):
    _, rev = fake
    target = tmp_path / "clinical.csv"
    target.write_bytes(b"old")
    gfj.use_asset("R1", path=str(target), quiet=True)
    assert target.read_bytes() == b"a,b\n1,2\n"
    assert rev.data[0].fetches == 1


def test_use_asset_rejects_a_digest_mismatch(tmp_path, fake):
    _, rev = fake
    rev.fetch()
    rev.data[0].hash = "0" * 64
    with pytest.raises(RuntimeError, match="did not match"):
        gfj.use_asset("R1", directory=str(tmp_path), quiet=True)
    assert not os.path.exists(tmp_path / "clinical.csv")

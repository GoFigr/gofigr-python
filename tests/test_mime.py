"""\
Copyright (c) 2026, Flagstaff Solutions, LLC
All rights reserved.

The GoFigr figure MIME bundle: payload shape, and the in-place update of the
figure output after publish.
"""
import io
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import PIL

from gofigr import publisher as publisher_module
from gofigr.backends.matplotlib import MatplotlibBackend
from gofigr.mime import GOFIGR_FIGURE_MIME, build_figure_payload
from gofigr.publisher import Publisher
from gofigr.watermarks import DefaultWatermark
from gofigr.widget import DetailedWidget

DATA_DIR = Path(__file__).parent / "data"


def _png_bytes():
    with open(DATA_DIR / 'plot.png', 'rb') as f:
        return f.read()


def _rev(mock_gf):
    rev = mock_gf.Revision(api_id="7372fc16-ee27-4293-b6ba-5c15f7e5d3c2")
    rev._short_id = "ab12CD34ef"
    rev.created_on = datetime.now(timezone.utc)
    rev.size_bytes = 12345
    raw = _png_bytes()
    img = PIL.Image.open(io.BytesIO(raw))
    img.load()
    wm = DefaultWatermark().apply(img, rev)
    bio = io.BytesIO()
    wm.save(bio, format='png')
    rev.image_data = [
        mock_gf.ImageData(name="figure", format="png", data=raw, is_watermarked=False),
        mock_gf.ImageData(name="figure", format="png", data=bio.getvalue(), is_watermarked=True),
        mock_gf.ImageData(name="figure", format="svg", data=b"<svg/>", is_watermarked=False),
    ]
    return rev, raw


class TestFigurePayload:
    def test_payload_shape(self, mock_gf):
        rev, raw = _rev(mock_gf)
        payload = build_figure_payload(rev, raw_png=raw, watermark=DefaultWatermark(), image_size=(640, 480))
        assert payload["version"] == 1
        assert payload["revision"]["api_id"] == "7372fc16-ee27-4293-b6ba-5c15f7e5d3c2"
        assert payload["revision"]["short_id"] == "ab12CD34ef"
        assert payload["revision"]["url"].endswith("/r/ab12CD34ef")
        assert payload["watermark"]["url"] == payload["revision"]["url"]
        assert payload["watermark"]["qr"] is True
        assert payload["watermark"]["font_px"] == 14
        assert payload["image"]["embedded"] is True
        assert payload["image"]["width"] == 640
        assert payload["image"]["b64"]
        assert {(f["format"], f["watermarked"]) for f in payload["formats"]} == {("png", False), ("png", True), ("svg", False)}
        json.dumps(payload)  # serializable

    def test_large_image_is_referenced_not_embedded(self, mock_gf):
        rev, _ = _rev(mock_gf)
        payload = build_figure_payload(rev, raw_png=b"x" * 2_000_000)
        assert payload["image"]["embedded"] is False
        assert payload["image"]["b64"] is None


class TestUpdateFigureDisplay:
    def test_bundle_replaces_the_shown_image(self, mock_gf, monkeypatch):
        rev, raw = _rev(mock_gf)
        calls = []
        monkeypatch.setattr(publisher_module, 'ipython_update_display',
                            lambda data, metadata=None, display_id=None, raw=False: calls.append((data, display_id, raw)))
        pub = object.__new__(Publisher)
        pub.gf = mock_gf
        pub.watermark = DefaultWatermark()
        widget = DetailedWidget(rev)
        ok = pub._update_figure_display(SimpleNamespace(display_id='d1'), rev, MatplotlibBackend(), None,
                                        rev.image_data[1], widget)
        assert ok is True
        data, display_id, is_raw = calls[0]
        assert display_id == 'd1' and is_raw is True
        # Compatibility: the watermarked PNG and an HTML view (image + widget).
        assert data['image/png']
        assert data['text/html'].startswith('<img src="data:image/png;base64,')
        assert 'View on GoFigr' in data['text/html']
        # The GoFigr representation carries the RAW image for client-side watermarking.
        payload = data[GOFIGR_FIGURE_MIME]
        assert payload['image']['embedded'] and payload['interactive'] is None
        assert payload['revision']['short_id'] == 'ab12CD34ef'

    def test_without_ipython_falls_back(self, mock_gf, monkeypatch):
        rev, _ = _rev(mock_gf)
        monkeypatch.setattr(publisher_module, 'ipython_update_display', None)
        pub = object.__new__(Publisher)
        pub.gf = mock_gf
        pub.watermark = DefaultWatermark()
        assert pub._update_figure_display(SimpleNamespace(display_id='d1'), rev, MatplotlibBackend(), None,
                                          None, DetailedWidget(rev)) is False
        assert pub._update_figure_display(None, rev, MatplotlibBackend(), None, None, DetailedWidget(rev)) is False


class TestDeferredDisplayInsideOutputWidget:
    def test_bundle_is_displayed_once_when_captured_by_an_output_widget(self, mock_gf, monkeypatch):
        rev, _ = _rev(mock_gf)
        shown = []
        monkeypatch.setattr(publisher_module, 'display',
                            lambda data, metadata=None, raw=False, **kw: shown.append((data, raw)))
        pub = object.__new__(Publisher)
        pub.gf = mock_gf
        pub.watermark = DefaultWatermark()
        ok = pub._display_figure_bundle(rev, MatplotlibBackend(), None, rev.image_data[1], DetailedWidget(rev))
        assert ok is True
        data, is_raw = shown[0]
        assert is_raw is True
        assert GOFIGR_FIGURE_MIME in data and data['image/png'] and 'View on GoFigr' in data['text/html']

    def test_inside_output_widget_detection_is_safe_without_a_kernel(self):
        assert publisher_module._inside_output_widget() is False

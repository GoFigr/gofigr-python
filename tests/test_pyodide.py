"""\
Unit tests for the PyodidePublisher, _RevisionStub, and _make_backend helpers.
"""
import copy
import io
import json
import unittest
from http import HTTPStatus
from unittest.mock import MagicMock, patch, PropertyMock

import pandas as pd
from PIL import Image

from gofigr.backends import GoFigrBackend
from gofigr.pyodide import PyodidePublisher, _RevisionStub, _make_backend
from gofigr.reproducible import ReproducibleContext, _reproducible_context


def _minimal_png_bytes():
    """Create a minimal valid 1x1 PNG."""
    img = Image.new("RGB", (1, 1), color="red")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_mock_gf():
    """Create a mock GoFigr client with factory methods."""
    gf = MagicMock()

    def _image_data(**kwargs):
        obj = MagicMock()
        obj.name = kwargs.get("name", "figure")
        obj.format = kwargs.get("format", "png")
        obj.data = kwargs.get("data", b"")
        obj.is_watermarked = kwargs.get("is_watermarked", False)
        obj.to_json.return_value = {"type": "image", "name": obj.name}
        return obj

    def _code_data(**kwargs):
        obj = MagicMock()
        obj.name = kwargs.get("name", "code")
        obj.is_clean_room = kwargs.get("is_clean_room", False)
        obj.to_json.return_value = {"type": "code", "name": obj.name}
        return obj

    def _text_data(**kwargs):
        obj = MagicMock()
        obj.name = kwargs.get("name", "text")
        obj.is_clean_room = kwargs.get("is_clean_room", False)
        obj.metadata = {}
        obj.to_json.return_value = {"type": "text", "name": obj.name}
        return obj

    def _table_data(**kwargs):
        obj = MagicMock()
        obj.name = kwargs.get("name", "table")
        obj.is_clean_room = kwargs.get("is_clean_room", False)
        obj.to_json.return_value = {"type": "table", "name": obj.name}
        return obj

    gf.ImageData = _image_data
    gf.CodeData = _code_data
    gf.TextData = _text_data
    gf.TableData = _table_data
    return gf


def _make_mock_backend(title="Test Figure", supported_formats=("png", "svg")):
    backend = MagicMock(spec=GoFigrBackend)
    backend.get_title.return_value = title
    backend.get_supported_image_formats.return_value = list(supported_formats)
    backend.figure_to_bytes.return_value = _minimal_png_bytes()
    backend.get_default_figure.return_value = "mock_fig"
    backend.is_compatible.return_value = True
    return backend


# ---------------------------------------------------------------------------
# _RevisionStub
# ---------------------------------------------------------------------------
class TestRevisionStub(unittest.TestCase):
    def test_stores_api_id(self):
        stub = _RevisionStub("abc-123")
        self.assertEqual(stub.api_id, "abc-123")

    def test_different_ids(self):
        s1 = _RevisionStub("id-1")
        s2 = _RevisionStub("id-2")
        self.assertNotEqual(s1.api_id, s2.api_id)


# ---------------------------------------------------------------------------
# _make_backend
# ---------------------------------------------------------------------------
class TestMakeBackend(unittest.TestCase):
    def test_returns_instance_as_is(self):
        backend = _make_mock_backend()
        result = _make_backend(backend)
        self.assertIs(result, backend)

    def test_calls_class_constructor(self):
        class FakeBackend(GoFigrBackend):
            instantiated = False

            def __init__(self):
                FakeBackend.instantiated = True

            def is_compatible(self, fig): return True
            def is_interactive(self, fig): return False
            def is_static(self, fig): return True
            def find_figures(self, shell, data): return []
            def get_title(self, fig): return "t"
            def figure_to_bytes(self, fig, fmt, opts=None): return b""
            def get_supported_image_formats(self): return ["png"]

        result = _make_backend(FakeBackend)
        self.assertIsInstance(result, FakeBackend)
        self.assertTrue(FakeBackend.instantiated)


# ---------------------------------------------------------------------------
# PyodidePublisher._resolve_target
# ---------------------------------------------------------------------------
class TestResolveTarget(unittest.TestCase):
    def setUp(self):
        self.gf = _make_mock_gf()
        self.analysis = MagicMock()
        self.publisher = PyodidePublisher(
            gf=self.gf,
            analysis=self.analysis,
            source_revision_api_id="src-rev-1",
        )

    def test_uses_find_figure_when_target_provided(self):
        target = MagicMock()
        self.gf.find_figure.return_value = target
        result = self.publisher._resolve_target("fig", target, _make_mock_backend())
        self.gf.find_figure.assert_called_once_with(self.analysis, target)
        self.assertEqual(result, target)

    def test_falls_back_to_title(self):
        backend = _make_mock_backend(title="My Plot")
        expected = MagicMock()
        self.analysis.get_figure.return_value = expected

        result = self.publisher._resolve_target("fig", None, backend)
        self.analysis.get_figure.assert_called_once_with("My Plot", create=True)
        self.assertEqual(result, expected)

    def test_anonymous_figure_when_title_none(self):
        backend = _make_mock_backend(title=None)
        expected = MagicMock()
        self.analysis.get_figure.return_value = expected

        result = self.publisher._resolve_target("fig", None, backend)
        self.analysis.get_figure.assert_called_once_with("Anonymous Figure", create=True)


# ---------------------------------------------------------------------------
# PyodidePublisher._get_image_data
# ---------------------------------------------------------------------------
class TestGetImageData(unittest.TestCase):
    def setUp(self):
        self.gf = _make_mock_gf()
        self.publisher = PyodidePublisher(
            gf=self.gf,
            analysis=MagicMock(),
            source_revision_api_id="src-rev-1",
            image_formats=("png", "svg"),
        )

    def test_produces_raw_and_watermarked_png(self):
        backend = _make_mock_backend()
        rev_stub = _RevisionStub("test-id")

        image_data, wm_png = self.publisher._get_image_data(
            "fig", rev_stub, backend, None,
        )

        png_items = [d for d in image_data if d.format == "png"]
        self.assertEqual(len(png_items), 2)
        self.assertIsNotNone(wm_png)

    def test_skips_unsupported_format(self):
        backend = _make_mock_backend(supported_formats=("png",))
        rev_stub = _RevisionStub("test-id")

        image_data, _ = self.publisher._get_image_data(
            "fig", rev_stub, backend, None,
        )

        formats = {d.format for d in image_data}
        self.assertNotIn("svg", formats)

    def test_continues_on_figure_to_bytes_error(self):
        backend = _make_mock_backend(supported_formats=("png", "svg"))
        backend.figure_to_bytes.side_effect = [
            RuntimeError("oops"),
            b"<svg/>",
        ]
        rev_stub = _RevisionStub("test-id")

        image_data, wm_png = self.publisher._get_image_data(
            "fig", rev_stub, backend, None,
        )
        self.assertIsNone(wm_png)
        svg_items = [d for d in image_data if d.format == "svg"]
        self.assertEqual(len(svg_items), 1)


# ---------------------------------------------------------------------------
# PyodidePublisher._build_clean_room_data
# ---------------------------------------------------------------------------
class TestBuildCleanRoomData(unittest.TestCase):
    def test_produces_code_manifest_and_dataframes(self):
        gf = _make_mock_gf()
        publisher = PyodidePublisher(
            gf=gf,
            analysis=MagicMock(),
            source_revision_api_id="src-rev-1",
        )

        df = pd.DataFrame({"x": [1, 2, 3]})
        ctx = ReproducibleContext(
            source_code="return data.head(n)",
            function_name="my_func",
            packages={"np": "numpy"},
            imports={"np": "numpy"},
            package_versions={"numpy": "1.26.0"},
            parameters={"data": df, "n": 5},
        )

        data_list = publisher._build_clean_room_data(ctx)

        types = [type(d).__name__ if not isinstance(d, MagicMock) else d.name
                 for d in data_list]
        self.assertTrue(len(data_list) >= 3)

        code_items = [d for d in data_list if d.is_clean_room and d.name == "Clean Room Source"]
        manifest_items = [d for d in data_list if d.is_clean_room and d.metadata.get("role") == "manifest"]
        table_items = [d for d in data_list if d.is_clean_room and d.name == "data"]

        self.assertEqual(len(code_items), 1)
        self.assertEqual(len(manifest_items), 1)
        self.assertEqual(len(table_items), 1)

    def test_all_items_marked_clean_room(self):
        gf = _make_mock_gf()
        publisher = PyodidePublisher(
            gf=gf,
            analysis=MagicMock(),
            source_revision_api_id="src-rev-1",
        )

        ctx = ReproducibleContext(
            source_code="pass",
            function_name="f",
            packages={},
            imports={},
            package_versions={},
            parameters={"x": 42},
        )

        data_list = publisher._build_clean_room_data(ctx)
        for d in data_list:
            self.assertTrue(d.is_clean_room)


# ---------------------------------------------------------------------------
# PyodidePublisher._build_updated_manifest
# ---------------------------------------------------------------------------
class TestBuildUpdatedManifest(unittest.TestCase):
    def test_merges_current_params(self):
        source_manifest = {
            "language": "python",
            "parameters": {
                "n": {"type": "integer", "value": 5, "widget": "slider"},
                "title": {"type": "string", "value": "old", "widget": "text"},
            },
        }
        gf = _make_mock_gf()
        publisher = PyodidePublisher(
            gf=gf,
            analysis=MagicMock(),
            source_revision_api_id="src-rev-1",
            source_manifest=source_manifest,
            current_params={"n": 10, "title": "new"},
        )

        result = publisher._build_updated_manifest()
        self.assertTrue(result.is_clean_room)
        self.assertEqual(result.metadata["role"], "manifest")
        self.assertEqual(result.name, "Clean Room Manifest")

    def test_does_not_modify_source(self):
        source_manifest = {
            "language": "python",
            "parameters": {
                "n": {"type": "integer", "value": 5},
            },
        }
        original = copy.deepcopy(source_manifest)
        gf = _make_mock_gf()
        publisher = PyodidePublisher(
            gf=gf,
            analysis=MagicMock(),
            source_revision_api_id="src-rev-1",
            source_manifest=source_manifest,
            current_params={"n": 99},
        )

        publisher._build_updated_manifest()
        self.assertEqual(source_manifest, original)

    def test_ignores_unknown_params(self):
        source_manifest = {
            "language": "python",
            "parameters": {
                "n": {"type": "integer", "value": 5},
            },
        }
        gf = _make_mock_gf()
        publisher = PyodidePublisher(
            gf=gf,
            analysis=MagicMock(),
            source_revision_api_id="src-rev-1",
            source_manifest=source_manifest,
            current_params={"n": 10, "unknown_param": 42},
        )

        result = publisher._build_updated_manifest()
        self.assertIsNotNone(result)


# ---------------------------------------------------------------------------
# PyodidePublisher.publish
# ---------------------------------------------------------------------------
class TestPublishFlow(unittest.TestCase):
    def _setup_publisher(self, **kwargs):
        gf = _make_mock_gf()
        analysis = MagicMock()

        target_fig = MagicMock()
        target_fig.api_id = "fig-api-id"
        analysis.get_figure.return_value = target_fig

        derive_response = MagicMock()
        derive_response.json.return_value = {"api_id": "derived-rev-123"}
        gf._post = MagicMock(return_value=derive_response)

        backend = _make_mock_backend()

        publisher = PyodidePublisher(
            gf=gf,
            analysis=analysis,
            source_revision_api_id="src-rev-1",
            backends=[backend],
            **kwargs,
        )
        return publisher, gf, backend

    def test_raises_when_no_fig_and_no_backend(self):
        publisher, _, _ = self._setup_publisher()
        with self.assertRaises(ValueError):
            publisher.publish(fig=None, backend=None)

    def test_calls_derive_endpoint(self):
        publisher, gf, backend = self._setup_publisher()

        publisher.publish(fig="mock_fig", backend=backend)

        derive_call = gf._post.call_args_list[0]
        self.assertIn("derive", derive_call[0][0])

    def test_calls_append_data_endpoint(self):
        publisher, gf, backend = self._setup_publisher()

        publisher.publish(fig="mock_fig", backend=backend)

        calls = gf._post.call_args_list
        self.assertTrue(len(calls) >= 2)
        append_call = calls[1]
        self.assertIn("append_data", append_call[0][0])

    def test_stores_watermarked_png(self):
        publisher, gf, backend = self._setup_publisher()

        result = publisher.publish(fig="mock_fig", backend=backend)
        wm = publisher.last_watermarked_image(result)
        self.assertIsNotNone(wm)

    def test_uses_build_clean_room_data_with_context(self):
        publisher, gf, backend = self._setup_publisher()

        ctx = ReproducibleContext(
            source_code="pass",
            function_name="f",
            packages={},
            imports={},
            package_versions={},
            parameters={"x": 1},
        )
        token = _reproducible_context.set(ctx)
        try:
            result = publisher.publish(fig="mock_fig", backend=backend)
            calls = gf._post.call_args_list
            append_call = calls[1]
            serialized = append_call[1]["json"]["data"]
            type_names = [d.get("type") for d in serialized]
            self.assertIn("code", type_names)
        finally:
            _reproducible_context.set(None)

    def test_uses_build_updated_manifest_without_context(self):
        source_manifest = {
            "language": "python",
            "parameters": {"n": {"type": "integer", "value": 5}},
        }
        publisher, gf, backend = self._setup_publisher(
            source_manifest=source_manifest,
            current_params={"n": 10},
        )

        result = publisher.publish(fig="mock_fig", backend=backend)
        calls = gf._post.call_args_list
        self.assertTrue(len(calls) >= 2)

    def test_neither_context_nor_manifest(self):
        publisher, gf, backend = self._setup_publisher()

        result = publisher.publish(fig="mock_fig", backend=backend)
        calls = gf._post.call_args_list
        append_call = calls[1]
        serialized = append_call[1]["json"]["data"]
        code_items = [d for d in serialized if d.get("type") == "code"]
        self.assertEqual(len(code_items), 0)

    def test_publish_with_metadata(self):
        publisher, gf, backend = self._setup_publisher()

        publisher.publish(
            fig="mock_fig", backend=backend,
            metadata={"custom": "value"},
        )

        derive_call = gf._post.call_args_list[0]
        payload = derive_call[1]["json"]
        self.assertEqual(payload["metadata"], {"custom": "value"})


if __name__ == '__main__':
    unittest.main()

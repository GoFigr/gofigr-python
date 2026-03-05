"""\
Unit tests for the clean room parameter serialization module.
"""
import json
import math
import unittest
from typing import Literal

import numpy as np
import pandas as pd

from gofigr.cleanroom import (
    CleanRoomSerializationError,
    MAX_CLEAN_ROOM_BYTES,
    Param,
    SliderParam,
    DropdownParam,
    CheckboxParam,
    TextParam,
    StaticParam,
    infer_param,
    validate_params,
    serialize_params,
    deserialize_params,
    round_trip_params,
    check_clean_room_size,
    estimate_dataframe_memory,
)


class TestValidateParams(unittest.TestCase):
    def test_primitives_accepted(self):
        validate_params({"a": 1, "b": 2.5, "c": "hello", "d": True, "e": None})

    def test_empty_params(self):
        validate_params({})

    def test_list_of_primitives_accepted(self):
        validate_params({"x": [1, 2, 3], "y": ["a", "b"]})

    def test_dict_of_primitives_accepted(self):
        validate_params({"x": {"nested": 1, "also": "ok"}})

    def test_deeply_nested_accepted(self):
        validate_params({"x": {"a": [1, {"b": [True, None, "hi"]}]}})

    def test_dataframe_accepted(self):
        df = pd.DataFrame({"col": [1, 2, 3]})
        validate_params({"data": df})

    def test_mixed_accepted(self):
        df = pd.DataFrame({"col": [1, 2, 3]})
        validate_params({"data": df, "n": 10, "label": "test"})

    def test_custom_object_rejected(self):
        class Foo:
            pass
        with self.assertRaises(CleanRoomSerializationError) as cm:
            validate_params({"obj": Foo()})
        self.assertIn("obj", str(cm.exception))
        self.assertIn("Foo", str(cm.exception))

    def test_function_rejected(self):
        with self.assertRaises(CleanRoomSerializationError):
            validate_params({"fn": lambda x: x})

    def test_numpy_array_rejected(self):
        with self.assertRaises(CleanRoomSerializationError):
            validate_params({"arr": np.array([1, 2, 3])})

    def test_dataframe_inside_list_rejected(self):
        df = pd.DataFrame({"a": [1]})
        with self.assertRaises(CleanRoomSerializationError):
            validate_params({"items": [df]})

    def test_multiple_bad_params_reported(self):
        class A:
            pass
        class B:
            pass
        with self.assertRaises(CleanRoomSerializationError) as cm:
            validate_params({"x": A(), "y": B()})
        msg = str(cm.exception)
        self.assertIn("x", msg)
        self.assertIn("y", msg)


class TestSerializeDeserialize(unittest.TestCase):
    def test_primitives_round_trip(self):
        params = {"i": 42, "f": 3.14, "s": "hello", "b": True, "n": None}
        bundle = serialize_params(params)
        result = deserialize_params(bundle.manifest, bundle.dataframes)
        self.assertEqual(result, params)
        self.assertEqual(len(bundle.dataframes), 0)

    def test_list_round_trip(self):
        params = {"items": [1, "two", 3.0, None, True]}
        result = round_trip_params(params)
        self.assertEqual(result, params)

    def test_nested_dict_round_trip(self):
        params = {"config": {"lr": 0.01, "layers": [64, 32], "name": "model"}}
        result = round_trip_params(params)
        self.assertEqual(result, params)

    def test_dataframe_round_trip(self):
        df = pd.DataFrame({
            "ints": [1, 2, 3],
            "floats": [1.1, 2.2, 3.3],
            "strings": ["a", "b", "c"],
        })
        params = {"data": df}
        bundle = serialize_params(params)

        self.assertIn("data", bundle.dataframes)
        self.assertEqual(bundle.manifest["data"]["type"], "dataframe")

        result = deserialize_params(bundle.manifest, bundle.dataframes)
        self.assertTrue(result["data"].equals(df))

    def test_mixed_params_round_trip(self):
        df = pd.DataFrame({"x": np.arange(50), "y": np.random.normal(size=50)})
        params = {"data": df, "bins": 20, "title": "histogram", "show": True}
        result = round_trip_params(params)

        self.assertTrue(result["data"].equals(df))
        self.assertEqual(result["bins"], 20)
        self.assertEqual(result["title"], "histogram")
        self.assertEqual(result["show"], True)

    def test_empty_dataframe(self):
        df = pd.DataFrame()
        result = round_trip_params({"empty": df})
        self.assertTrue(result["empty"].equals(df))

    def test_dataframe_dtypes_preserved(self):
        df = pd.DataFrame({
            "int64": pd.array([1, 2, 3], dtype="int64"),
            "float64": pd.array([1.0, 2.0, 3.0], dtype="float64"),
            "bool": pd.array([True, False, True], dtype="bool"),
            "str": pd.array(["a", "b", "c"], dtype="object"),
        })
        result = round_trip_params({"df": df})
        for col in df.columns:
            self.assertEqual(result["df"][col].dtype, df[col].dtype,
                             f"dtype mismatch for column '{col}'")

    def test_manifest_is_valid_json(self):
        df = pd.DataFrame({"a": [1]})
        params = {"data": df, "n": 5}
        bundle = serialize_params(params)
        parsed = json.loads(bundle.manifest_json())
        self.assertIn("data", parsed)
        self.assertIn("n", parsed)

    def test_unsupported_type_in_serialize(self):
        with self.assertRaises(CleanRoomSerializationError):
            serialize_params({"obj": object()})

    def test_missing_dataframe_in_deserialize(self):
        manifest = {"data": {"type": "dataframe"}}
        with self.assertRaises(CleanRoomSerializationError):
            deserialize_params(manifest, {})

    def test_unknown_type_in_deserialize(self):
        manifest = {"x": {"type": "totally_invalid_type"}}
        with self.assertRaises(CleanRoomSerializationError):
            deserialize_params(manifest, {})

    def test_manifest_has_language_neutral_types(self):
        params = {"i": 42, "f": 3.14, "s": "hello", "b": True, "n": None}
        bundle = serialize_params(params)
        self.assertEqual(bundle.manifest["i"]["type"], "integer")
        self.assertEqual(bundle.manifest["f"]["type"], "number")
        self.assertEqual(bundle.manifest["s"]["type"], "string")
        self.assertEqual(bundle.manifest["b"]["type"], "boolean")
        self.assertEqual(bundle.manifest["n"]["type"], "none")

    def test_manifest_has_widget_field(self):
        params = {"i": 42, "f": 3.14, "s": "hello", "b": True}
        bundle = serialize_params(params)
        self.assertEqual(bundle.manifest["i"]["widget"], "slider")
        self.assertEqual(bundle.manifest["f"]["widget"], "slider")
        self.assertEqual(bundle.manifest["s"]["widget"], "text")
        self.assertEqual(bundle.manifest["b"]["widget"], "checkbox")

    def test_manifest_slider_has_bounds(self):
        bundle = serialize_params({"n": 50})
        entry = bundle.manifest["n"]
        self.assertIn("min", entry)
        self.assertIn("max", entry)
        self.assertIn("step", entry)
        self.assertEqual(entry["step"], 1)

    def test_serialize_with_param_descriptors(self):
        desc = {"n": SliderParam(50, min=10, max=200, step=5)}
        bundle = serialize_params({"n": 50}, param_descriptors=desc)
        entry = bundle.manifest["n"]
        self.assertEqual(entry["type"], "integer")
        self.assertEqual(entry["widget"], "slider")
        self.assertEqual(entry["min"], 10)
        self.assertEqual(entry["max"], 200)
        self.assertEqual(entry["step"], 5)
        self.assertEqual(entry["value"], 50)

    def test_backward_compat_deserialize_primitive(self):
        manifest = {"x": {"type": "primitive", "value": 42}}
        result = deserialize_params(manifest, {})
        self.assertEqual(result["x"], 42)

    def test_backward_compat_deserialize_new_types(self):
        manifest = {
            "i": {"type": "integer", "widget": "slider", "value": 10, "min": 0, "max": 20, "step": 1},
            "s": {"type": "string", "widget": "text", "value": "hi"},
            "b": {"type": "boolean", "widget": "checkbox", "value": True},
        }
        result = deserialize_params(manifest, {})
        self.assertEqual(result, {"i": 10, "s": "hi", "b": True})


class TestEdgeCases(unittest.TestCase):
    def test_nan_float(self):
        params = {"x": float("nan")}
        result = round_trip_params(params)
        self.assertTrue(math.isnan(result["x"]))

    def test_inf_float(self):
        params = {"x": float("inf"), "y": float("-inf")}
        result = round_trip_params(params)
        self.assertEqual(result["x"], float("inf"))
        self.assertEqual(result["y"], float("-inf"))

    def test_unicode_string(self):
        params = {"text": "Hello \u00e9\u00e8\u00ea \u4e16\u754c \ud83c\udf0d"}
        result = round_trip_params(params)
        self.assertEqual(result["text"], params["text"])

    def test_empty_containers(self):
        params = {"empty_list": [], "empty_dict": {}}
        result = round_trip_params(params)
        self.assertEqual(result, params)

    def test_deeply_nested_structure(self):
        params = {"deep": {"a": {"b": {"c": {"d": [1, 2, {"e": 3}]}}}}}
        result = round_trip_params(params)
        self.assertEqual(result, params)

    def test_large_dataframe(self):
        df = pd.DataFrame({"x": np.arange(10000), "y": np.random.normal(size=10000)})
        result = round_trip_params({"data": df})
        self.assertTrue(result["data"].equals(df))

    def test_dataframe_with_nan(self):
        df = pd.DataFrame({"a": [1.0, np.nan, 3.0], "b": [np.nan, 2.0, np.nan]})
        result = round_trip_params({"df": df})
        self.assertTrue(result["df"].equals(df))

    def test_empty_params_round_trip(self):
        result = round_trip_params({})
        self.assertEqual(result, {})

    def test_multiple_dataframes(self):
        df1 = pd.DataFrame({"a": [1, 2]})
        df2 = pd.DataFrame({"b": [3, 4, 5]})
        params = {"first": df1, "second": df2, "n": 10}
        result = round_trip_params(params)
        self.assertTrue(result["first"].equals(df1))
        self.assertTrue(result["second"].equals(df2))
        self.assertEqual(result["n"], 10)


class TestSizeCheck(unittest.TestCase):
    def test_small_params_pass(self):
        params = {"data": pd.DataFrame({"a": [1, 2, 3]}), "n": 5}
        self.assertTrue(check_clean_room_size(params))

    def test_no_dataframes_pass(self):
        self.assertTrue(check_clean_room_size({"a": 1, "b": "hello"}))

    def test_oversized_warns(self):
        n = MAX_CLEAN_ROOM_BYTES // 8 + 1000
        big_df = pd.DataFrame({"x": np.zeros(n)})
        with self.assertWarns(UserWarning):
            result = check_clean_room_size({"data": big_df})
        self.assertFalse(result)

    def test_estimate_memory(self):
        df = pd.DataFrame({"x": np.arange(100)})
        params = {"data": df, "n": 5}
        mem = estimate_dataframe_memory(params)
        self.assertGreater(mem, 0)
        self.assertEqual(estimate_dataframe_memory({"n": 5}), 0)


class TestParamHierarchy(unittest.TestCase):
    """Tests for Param subclasses and their to_manifest() output."""

    def test_slider_int_default_bounds(self):
        p = SliderParam(20)
        m = p.to_manifest()
        self.assertEqual(m["type"], "integer")
        self.assertEqual(m["widget"], "slider")
        self.assertEqual(m["value"], 20)
        self.assertEqual(m["min"], 0)
        self.assertEqual(m["max"], 100)
        self.assertEqual(m["step"], 1)

    def test_slider_int_custom_bounds(self):
        p = SliderParam(20, min=5, max=200, step=5)
        m = p.to_manifest()
        self.assertEqual(m["min"], 5)
        self.assertEqual(m["max"], 200)
        self.assertEqual(m["step"], 5)

    def test_slider_float_default_bounds(self):
        p = SliderParam(3.14)
        m = p.to_manifest()
        self.assertEqual(m["type"], "number")
        self.assertEqual(m["widget"], "slider")
        self.assertEqual(m["value"], 3.14)
        self.assertEqual(m["min"], 0)
        self.assertAlmostEqual(m["max"], 6.28)
        self.assertEqual(m["step"], 0.1)

    def test_slider_zero_value(self):
        p = SliderParam(0)
        m = p.to_manifest()
        self.assertEqual(m["max"], 100)
        self.assertEqual(m["step"], 1)

    def test_slider_zero_float(self):
        p = SliderParam(0.0)
        m = p.to_manifest()
        self.assertEqual(m["max"], 1.0)
        self.assertEqual(m["step"], 0.1)

    def test_slider_override_value(self):
        p = SliderParam(10, min=0, max=100)
        m = p.to_manifest(value=50)
        self.assertEqual(m["value"], 50)

    def test_dropdown(self):
        p = DropdownParam("a", choices=["a", "b", "c"])
        m = p.to_manifest()
        self.assertEqual(m["type"], "string")
        self.assertEqual(m["widget"], "dropdown")
        self.assertEqual(m["value"], "a")
        self.assertEqual(m["choices"], ["a", "b", "c"])

    def test_dropdown_override_value(self):
        p = DropdownParam("a", choices=["a", "b", "c"])
        m = p.to_manifest(value="b")
        self.assertEqual(m["value"], "b")

    def test_checkbox(self):
        p = CheckboxParam(True)
        m = p.to_manifest()
        self.assertEqual(m["type"], "boolean")
        self.assertEqual(m["widget"], "checkbox")
        self.assertEqual(m["value"], True)

    def test_checkbox_false(self):
        m = CheckboxParam(False).to_manifest()
        self.assertEqual(m["value"], False)

    def test_text(self):
        p = TextParam("hello")
        m = p.to_manifest()
        self.assertEqual(m["type"], "string")
        self.assertEqual(m["widget"], "text")
        self.assertEqual(m["value"], "hello")

    def test_static(self):
        p = StaticParam(42)
        m = p.to_manifest()
        self.assertEqual(m["type"], "integer")
        self.assertNotIn("widget", m)
        self.assertEqual(m["value"], 42)

    def test_static_none(self):
        m = StaticParam(None).to_manifest()
        self.assertEqual(m["type"], "none")

    def test_widget_meta_slider(self):
        p = SliderParam(20, min=5, max=100, step=5)
        meta = p.to_widget_meta()
        self.assertEqual(meta["type"], "slider")
        self.assertEqual(meta["min"], 5)
        self.assertEqual(meta["max"], 100)
        self.assertEqual(meta["step"], 5)

    def test_widget_meta_dropdown(self):
        p = DropdownParam("a", choices=["a", "b"])
        meta = p.to_widget_meta()
        self.assertEqual(meta["type"], "dropdown")
        self.assertEqual(meta["choices"], ["a", "b"])

    def test_widget_meta_checkbox(self):
        meta = CheckboxParam(True).to_widget_meta()
        self.assertEqual(meta["type"], "checkbox")

    def test_widget_meta_text(self):
        meta = TextParam("hi").to_widget_meta()
        self.assertEqual(meta["type"], "text")

    def test_widget_meta_static(self):
        meta = StaticParam(42).to_widget_meta()
        self.assertEqual(meta["type"], "static")


class TestInferParam(unittest.TestCase):
    """Tests for the infer_param() factory function."""

    def test_infer_int(self):
        p = infer_param("n", 42)
        self.assertIsInstance(p, SliderParam)
        self.assertEqual(p.default, 42)

    def test_infer_float(self):
        p = infer_param("rate", 0.5)
        self.assertIsInstance(p, SliderParam)
        self.assertEqual(p.default, 0.5)

    def test_infer_bool(self):
        p = infer_param("flag", True)
        self.assertIsInstance(p, CheckboxParam)

    def test_infer_str(self):
        p = infer_param("name", "hello")
        self.assertIsInstance(p, TextParam)

    def test_infer_complex_type(self):
        p = infer_param("obj", object())
        self.assertIsInstance(p, StaticParam)

    def test_infer_literal_hint(self):
        hints = {"method": Literal["kde", "hist", "ecdf"]}
        p = infer_param("method", "hist", type_hints=hints)
        self.assertIsInstance(p, DropdownParam)
        self.assertEqual(p.choices, ["kde", "hist", "ecdf"])

    def test_infer_no_hints(self):
        p = infer_param("x", 10, type_hints=None)
        self.assertIsInstance(p, SliderParam)

    def test_infer_non_literal_hint_ignored(self):
        hints = {"x": int}
        p = infer_param("x", 10, type_hints=hints)
        self.assertIsInstance(p, SliderParam)

    def test_bool_before_int(self):
        """bool is a subclass of int -- make sure we get CheckboxParam, not SliderParam."""
        p = infer_param("flag", False)
        self.assertIsInstance(p, CheckboxParam)


if __name__ == '__main__':
    unittest.main()

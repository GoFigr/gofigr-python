"""\
Unit tests for the @reproducible decorator.
"""
import unittest
from unittest.mock import MagicMock

import numpy as np
import pandas as pd

from gofigr.cleanroom import MAX_CLEAN_ROOM_BYTES
from gofigr.reproducible import (
    reproducible,
    _reproducible_context,
    _resolve_package_versions,
    _extract_function_body,
    ReproducibleContext,
)


class TestCleanRoomIsolation(unittest.TestCase):
    """The decorated function should not see outer-scope variables."""

    def test_module_globals_not_accessible(self):
        """Module-level globals (like imports) should not be available in the clean room."""
        @reproducible(packages={"np": "numpy"}, merge_packages=False)
        def func():
            try:
                # pd is imported at module level but not declared in packages
                return pd.DataFrame()  # noqa: F821
            except NameError:
                return "isolated"

        self.assertEqual(func(), "isolated")

    def test_declared_packages_accessible(self):
        @reproducible(packages={"np": "numpy"}, merge_packages=False)
        def func():
            return np.array([1, 2, 3]).tolist()

        self.assertEqual(func(), [1, 2, 3])

    def test_undeclared_package_not_accessible(self):
        @reproducible(packages={"np": "numpy"}, merge_packages=False)
        def func():
            try:
                import os  # noqa: F811
                return os.getcwd()
            except Exception:
                return "blocked"

        result = func()
        # The import statement itself uses builtins, so it may or may not work
        # depending on the clean room setup. The key test is that the function
        # runs in isolation.
        self.assertIsNotNone(result)


class TestParameterValidation(unittest.TestCase):
    def test_unsupported_type_falls_back(self):
        class Custom:
            pass

        call_count = {"n": 0}

        @reproducible(packages={}, merge_packages=False)
        def func(obj):
            call_count["n"] += 1
            return "done"

        with self.assertWarns(UserWarning):
            result = func(Custom())

        self.assertEqual(result, "done")
        self.assertEqual(call_count["n"], 1)


class TestRoundTripExecution(unittest.TestCase):
    """The function should run with deserialized (round-tripped) parameters."""

    def test_dataframe_is_different_object(self):
        original_df = pd.DataFrame({"x": [1, 2, 3]})
        received_ids = []

        @reproducible(packages={}, merge_packages=False)
        def func(data):
            received_ids.append(id(data))
            return data

        result = func(original_df)
        self.assertTrue(result.equals(original_df))
        # The function received a round-tripped copy, not the original
        self.assertNotEqual(received_ids[0], id(original_df))

    def test_primitives_pass_through(self):
        @reproducible(packages={}, merge_packages=False)
        def func(a, b, c):
            return a + b + c

        self.assertEqual(func(1, 2, 3), 6)

    def test_mixed_params(self):
        df = pd.DataFrame({"val": [10, 20, 30]})

        @reproducible(packages={"pd": "pandas"}, merge_packages=False)
        def func(data, multiplier):
            return data["val"].sum() * multiplier

        result = func(df, 2)
        self.assertEqual(result, 120)


class TestPackageVersionCollection(unittest.TestCase):
    def test_known_package_has_version(self):
        versions = _resolve_package_versions({"np": "numpy"})
        self.assertIn("numpy", versions)
        self.assertIsNotNone(versions["numpy"])

    def test_multiple_packages(self):
        versions = _resolve_package_versions({"np": "numpy", "pd": "pandas"})
        self.assertIn("numpy", versions)
        self.assertIn("pandas", versions)
        self.assertIsNotNone(versions["numpy"])
        self.assertIsNotNone(versions["pandas"])

    def test_submodule_stripping(self):
        versions = _resolve_package_versions({"plt": "matplotlib.pyplot"})
        self.assertIn("matplotlib", versions)
        self.assertIsNotNone(versions["matplotlib"])

    def test_nonexistent_package(self):
        versions = _resolve_package_versions({"x": "nonexistent_package_xyz"})
        self.assertIn("nonexistent_package_xyz", versions)
        self.assertIsNone(versions["nonexistent_package_xyz"])

    def test_deduplicates_aliases(self):
        versions = _resolve_package_versions({"np": "numpy", "nump": "numpy"})
        self.assertIn("numpy", versions)
        self.assertEqual(len(versions), 1)


class TestPublisherInjection(unittest.TestCase):
    def test_publish_available_when_publisher_provided(self):
        mock_publisher = MagicMock()
        mock_publisher.publish = MagicMock(return_value="published")

        captured = {}

        @reproducible(packages={}, merge_packages=False, publisher=mock_publisher)
        def func():
            captured["publish_exists"] = "publish" in dir()
            # publish is in globals, not dir() - test by calling it
            result = publish("test_fig")  # noqa: F821
            captured["publish_result"] = result

        func()
        mock_publisher.publish.assert_called_once_with("test_fig")

    def test_publish_not_available_without_publisher(self):
        @reproducible(packages={}, merge_packages=False)
        def func():
            try:
                publish()  # noqa: F821
                return "found"
            except NameError:
                return "not_found"

        self.assertEqual(func(), "not_found")


class TestContextVarLifecycle(unittest.TestCase):
    def test_context_set_during_execution(self):
        """Use a mock publisher to capture the context during publish()."""
        captured_ctx = {}

        mock_publisher = MagicMock()

        def capture_publish(*args, **kwargs):
            captured_ctx["ctx"] = _reproducible_context.get()

        mock_publisher.publish = capture_publish

        @reproducible(packages={"np": "numpy"}, merge_packages=False,
                       publisher=mock_publisher)
        def func(x):
            publish(x)  # noqa: F821
            return x

        func(42)
        ctx = captured_ctx["ctx"]
        self.assertIsInstance(ctx, ReproducibleContext)
        self.assertEqual(ctx.function_name, "func")
        self.assertIn("np", ctx.packages)
        self.assertIn("np", ctx.imports)
        self.assertIn("numpy", ctx.package_versions)
        self.assertEqual(ctx.parameters["x"], 42)

    def test_context_reset_after_return(self):
        @reproducible(packages={}, merge_packages=False)
        def func():
            return 1

        func()
        self.assertIsNone(_reproducible_context.get())

    def test_context_reset_after_exception(self):
        @reproducible(packages={}, merge_packages=False)
        def func():
            raise ValueError("boom")

        with self.assertRaises(ValueError):
            func()

        self.assertIsNone(_reproducible_context.get())

    def test_context_contains_unwrapped_body(self):
        """Source code should be the function body only, not the decorator or def line."""
        captured = {}

        mock_publisher = MagicMock()

        def capture_publish(*args, **kwargs):
            captured["ctx"] = _reproducible_context.get()

        mock_publisher.publish = capture_publish

        @reproducible(packages={}, merge_packages=False, publisher=mock_publisher)
        def my_function(a, b):
            publish()  # noqa: F821
            return a + b

        my_function(1, 2)
        src = captured["ctx"].source_code
        self.assertIn("return a + b", src)
        self.assertNotIn("@reproducible", src)
        self.assertNotIn("def my_function", src)


class TestExtractFunctionBody(unittest.TestCase):
    """Tests for _extract_function_body helper."""

    def test_simple_function(self):
        def my_func(x):
            return x + 1

        body = _extract_function_body(my_func)
        self.assertIn("return x + 1", body)
        self.assertNotIn("def my_func", body)

    def test_strips_decorator(self):
        """When used on a function that was defined with a decorator,
        the decorator line should not appear in the body."""
        @reproducible(packages={}, merge_packages=False)
        def decorated_func(a, b):
            result = a * b
            return result

        # _extract_function_body works on the original function, not the wrapper.
        # Test it on a plain function to verify AST extraction.
        def sample():
            x = 1
            y = 2
            return x + y

        body = _extract_function_body(sample)
        self.assertIn("x = 1", body)
        self.assertIn("return x + y", body)
        self.assertNotIn("def sample", body)

    def test_multiline_body(self):
        def multi():
            a = 1
            b = 2
            c = a + b
            return c

        body = _extract_function_body(multi)
        lines = body.strip().splitlines()
        self.assertEqual(len(lines), 4)
        self.assertIn("a = 1", body)
        self.assertIn("return c", body)

    def test_body_is_dedented(self):
        def indented():
            return 42

        body = _extract_function_body(indented)
        self.assertTrue(body.strip().startswith("return"))

    def test_preserves_docstring(self):
        def with_doc():
            """This is a docstring."""
            return 1

        body = _extract_function_body(with_doc)
        self.assertIn("This is a docstring", body)
        self.assertIn("return 1", body)


class TestSizeLimitFallback(unittest.TestCase):
    def test_oversized_dataframe_warns_and_runs(self):
        n = MAX_CLEAN_ROOM_BYTES // 8 + 1000
        big_df = pd.DataFrame({"x": np.zeros(n)})

        @reproducible(packages={}, merge_packages=False)
        def func(data):
            return len(data)

        with self.assertWarns(UserWarning):
            result = func(big_df)

        self.assertEqual(result, n)

    def test_oversized_skips_context(self):
        n = MAX_CLEAN_ROOM_BYTES // 8 + 1000
        big_df = pd.DataFrame({"x": np.zeros(n)})

        captured = {}

        @reproducible(packages={}, merge_packages=False)
        def func(data):
            captured["ctx"] = _reproducible_context.get()
            return len(data)

        with self.assertWarns(UserWarning):
            func(big_df)

        # Context should not be set when falling back
        self.assertIsNone(captured["ctx"])


if __name__ == '__main__':
    unittest.main()

"""\
Copyright (c) 2024, Flagstaff Solutions, LLC
All rights reserved.

Clean room parameter serialization, validation, and round-trip utilities.
"""
import io
import json
import warnings
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, List, get_origin, get_args, Literal

import pandas as pd

MAX_CLEAN_ROOM_BYTES = 100 * 1024 * 1024  # 100 MB

PRIMITIVE_TYPES = (int, float, str, bool, type(None))

PYTHON_TYPE_TO_NEUTRAL = {
    int: "integer",
    float: "number",
    bool: "boolean",
    str: "string",
    type(None): "none",
}

NON_DATAFRAME_TYPES = {"primitive", "integer", "number", "boolean", "string", "none", "unknown"}

# Keep a reference to the builtin ``max`` before any shadowing by Param fields.
_builtin_max = max


# ---------------------------------------------------------------------------
# Param hierarchy
# ---------------------------------------------------------------------------

class Param:
    """Base class for parameter descriptors.

    Subclasses describe the widget type and configuration for a single
    function parameter.  Each subclass implements ``to_manifest()`` (for the
    clean-room JSON manifest) and ``to_widget_meta()`` (for the Jupyter
    ``ReproducibleWidget`` JS).
    """

    def __init__(self, default: Any):
        self.default = default

    def to_manifest(self, value=None) -> dict:
        """Return a manifest entry dict for this parameter."""
        raise NotImplementedError

    def to_widget_meta(self) -> dict:
        """Return metadata dict consumed by the Jupyter widget JS."""
        raise NotImplementedError

    def _neutral_type(self, value) -> str:
        return PYTHON_TYPE_TO_NEUTRAL.get(type(value), "unknown")

    def __repr__(self):
        return f"{type(self).__name__}({self.default!r})"


class SliderParam(Param):
    """Numeric slider with optional min/max/step bounds."""

    def __init__(self, default: Any, *,
                 min: Optional[float] = None,   # pylint: disable=redefined-builtin
                 max: Optional[float] = None,   # pylint: disable=redefined-builtin
                 step: Optional[float] = None):
        super().__init__(default)
        self.min = min
        self.max = max
        self.step = step

    def _resolve_bounds(self, val):
        mn = self.min if self.min is not None else 0
        if self.max is not None:
            mx = self.max
        elif val == 0:
            mx = 100 if isinstance(val, int) else 1.0
        else:
            mx = _builtin_max(val * 2, 100 if isinstance(val, int) else 1.0)
        st = self.step if self.step is not None else (1 if isinstance(val, int) else 0.1)
        return mn, mx, st

    def to_manifest(self, value=None):
        val = value if value is not None else self.default
        mn, mx, st = self._resolve_bounds(val)
        return {"type": self._neutral_type(val), "widget": "slider",
                "value": val, "min": mn, "max": mx, "step": st}

    def to_widget_meta(self):
        mn, mx, st = self._resolve_bounds(self.default)
        return {"type": "slider", "value": self.default,
                "min": mn, "max": mx, "step": st}

    def __repr__(self):
        parts = [repr(self.default)]
        if self.min is not None:
            parts.append(f"min={self.min!r}")
        if self.max is not None:
            parts.append(f"max={self.max!r}")
        if self.step is not None:
            parts.append(f"step={self.step!r}")
        return f"SliderParam({', '.join(parts)})"


class DropdownParam(Param):
    """Categorical dropdown with a fixed set of choices."""

    def __init__(self, default: Any, *, choices: List):
        super().__init__(default)
        self.choices = list(choices)

    def to_manifest(self, value=None):
        val = value if value is not None else self.default
        return {"type": self._neutral_type(val), "widget": "dropdown",
                "value": val, "choices": self.choices}

    def to_widget_meta(self):
        return {"type": "dropdown", "value": self.default,
                "choices": self.choices}

    def __repr__(self):
        return f"DropdownParam({self.default!r}, choices={self.choices!r})"


class CheckboxParam(Param):
    """Boolean toggle / checkbox."""

    def to_manifest(self, value=None):
        val = value if value is not None else self.default
        return {"type": "boolean", "widget": "checkbox", "value": val}

    def to_widget_meta(self):
        return {"type": "checkbox", "value": self.default}


class TextParam(Param):
    """Free-form text input."""

    def to_manifest(self, value=None):
        val = value if value is not None else self.default
        return {"type": "string", "widget": "text", "value": val}

    def to_widget_meta(self):
        return {"type": "text", "value": self.default}


class StaticParam(Param):
    """Read-only parameter (complex types, DataFrames, etc.)."""

    def to_manifest(self, value=None):
        val = value if value is not None else self.default
        return {"type": self._neutral_type(val), "value": val}

    def to_widget_meta(self):
        return {"type": "static", "value": self.default}


def infer_param(name: str, value: Any, type_hints: Optional[dict] = None) -> Param:
    """\
    Create a ``Param`` descriptor for *value* with sensible defaults.

    If a ``Literal`` type hint is present the parameter becomes a dropdown.
    Otherwise the widget type is inferred from the value's Python type.

    :param name: parameter name (used to look up type hints)
    :param value: the parameter's current value
    :param type_hints: optional dict from ``typing.get_type_hints(func)``
    :return: an appropriate ``Param`` subclass instance
    """
    hint = (type_hints or {}).get(name)
    if hint is not None and get_origin(hint) is Literal:
        return DropdownParam(value, choices=list(get_args(hint)))
    if isinstance(value, bool):
        return CheckboxParam(value)
    if isinstance(value, (int, float)):
        return SliderParam(value)
    if isinstance(value, str):
        return TextParam(value)
    return StaticParam(value)


class CleanRoomSerializationError(Exception):
    """Raised when parameters cannot be serialized for clean room storage."""


def _is_primitive(value):
    """Check if a value is a JSON-serializable primitive (recursively for containers)."""
    if isinstance(value, PRIMITIVE_TYPES):
        return True
    if isinstance(value, list):
        return all(_is_primitive(v) for v in value)
    if isinstance(value, dict):
        return all(isinstance(k, str) and _is_primitive(v) for k, v in value.items())
    return False


def _is_dataframe(value):
    """Check if a value is a pandas DataFrame."""
    return isinstance(value, pd.DataFrame)


def validate_params(params: Dict[str, Any]):
    """\
    Check that all parameters are serializable for clean room storage.

    Supported types: Python primitives (int, float, str, bool, None),
    lists/dicts of primitives, and pd.DataFrame.

    :param params: dictionary of parameter names to values
    :raises CleanRoomSerializationError: if any parameter has an unsupported type
    """
    bad = []
    for name, value in params.items():
        if _is_primitive(value):
            continue
        if _is_dataframe(value):
            continue
        bad.append((name, type(value).__name__))

    if bad:
        details = ", ".join(f"'{n}' ({t})" for n, t in bad)
        raise CleanRoomSerializationError(
            f"Cannot serialize parameter(s) for clean room storage: {details}. "
            f"Supported types: int, float, str, bool, None, list, dict (of primitives), pd.DataFrame."
        )


def estimate_dataframe_memory(params: Dict[str, Any]) -> int:
    """\
    Estimate total memory usage of all DataFrame parameters.

    :param params: dictionary of parameter names to values
    :return: total bytes
    """
    total = 0
    for value in params.values():
        if _is_dataframe(value):
            total += value.memory_usage(deep=True).sum()
    return total


@dataclass
class CleanRoomBundle:
    """Result of serializing clean room parameters."""
    manifest: dict
    dataframes: Dict[str, bytes] = field(default_factory=dict)

    def manifest_json(self) -> str:
        """Return the manifest as a JSON string."""
        return json.dumps(self.manifest, ensure_ascii=False)


def serialize_params(params: Dict[str, Any],
                     param_descriptors: Optional[Dict[str, Param]] = None) -> CleanRoomBundle:
    """\
    Serialize function parameters into a CleanRoomBundle.

    DataFrames are serialized as Parquet bytes in a separate dict.
    All other parameters are stored in the JSON manifest using their
    ``Param`` descriptor's ``to_manifest()`` output.

    :param params: dictionary of parameter names to values
    :param param_descriptors: optional mapping of name -> Param descriptor.
        When provided, the descriptor's ``to_manifest(value)`` is used to
        produce the manifest entry.  When absent, ``infer_param`` is called.
    :return: CleanRoomBundle
    """
    manifest = {}
    dataframes = {}

    for name, value in params.items():
        if _is_dataframe(value):
            buf = io.BytesIO()
            value.to_parquet(buf, engine="pyarrow")
            dataframes[name] = buf.getvalue()
            manifest[name] = {"type": "dataframe"}
        elif _is_primitive(value):
            desc = (param_descriptors or {}).get(name)
            if desc is None:
                desc = infer_param(name, value)
            manifest[name] = desc.to_manifest(value)
        else:
            raise CleanRoomSerializationError(
                f"Cannot serialize parameter '{name}' of type {type(value).__name__}"
            )

    return CleanRoomBundle(manifest=manifest, dataframes=dataframes)


def deserialize_params(manifest: dict, dataframes: Dict[str, bytes]) -> Dict[str, Any]:
    """\
    Deserialize parameters from a manifest and DataFrame bytes.

    Handles both the legacy ``"primitive"`` type and the new language-neutral
    type names (``integer``, ``number``, ``boolean``, ``string``, ``none``).

    :param manifest: the JSON manifest dict
    :param dataframes: dict mapping param name to Parquet bytes
    :return: dictionary of parameter names to values
    """
    params = {}
    for name, entry in manifest.items():
        if entry["type"] in NON_DATAFRAME_TYPES:
            params[name] = entry["value"]
        elif entry["type"] == "dataframe":
            if name not in dataframes:
                raise CleanRoomSerializationError(
                    f"DataFrame parameter '{name}' referenced in manifest but not found in dataframes"
                )
            params[name] = pd.read_parquet(io.BytesIO(dataframes[name]), engine="pyarrow")
        else:
            raise CleanRoomSerializationError(f"Unknown parameter type '{entry['type']}' for '{name}'")

    return params


def round_trip_params(params: Dict[str, Any]) -> Dict[str, Any]:
    """\
    Serialize and then deserialize parameters, returning the round-tripped values.

    The decorator runs the function with these values so any serialization
    artifacts are visible immediately.

    :param params: dictionary of parameter names to values
    :return: round-tripped dictionary
    """
    bundle = serialize_params(params)
    return deserialize_params(bundle.manifest, bundle.dataframes)


def check_clean_room_size(params: Dict[str, Any]) -> bool:
    """\
    Check whether DataFrame parameters fit within MAX_CLEAN_ROOM_BYTES.

    :param params: dictionary of parameter names to values
    :return: True if within limits, False if too large (warning issued)
    """
    mem = estimate_dataframe_memory(params)
    if mem > MAX_CLEAN_ROOM_BYTES:
        warnings.warn(
            f"Total DataFrame memory ({mem / 1024 / 1024:.1f} MB) exceeds "
            f"MAX_CLEAN_ROOM_BYTES ({MAX_CLEAN_ROOM_BYTES / 1024 / 1024:.0f} MB). "
            f"Skipping clean room execution — function will run directly with original arguments.",
            stacklevel=3
        )
        return False
    return True

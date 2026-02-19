"""\
Copyright (c) 2024, Flagstaff Solutions, LLC
All rights reserved.

Clean room parameter serialization, validation, and round-trip utilities.
"""
import io
import json
import warnings
from dataclasses import dataclass, field
from typing import Any, Dict

import pandas as pd

MAX_CLEAN_ROOM_BYTES = 100 * 1024 * 1024  # 100 MB

PRIMITIVE_TYPES = (int, float, str, bool, type(None))


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


def serialize_params(params: Dict[str, Any]) -> CleanRoomBundle:
    """\
    Serialize function parameters into a CleanRoomBundle.

    Primitives are stored inline in the JSON manifest.
    DataFrames are serialized as Parquet bytes in a separate dict.

    :param params: dictionary of parameter names to values
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
            manifest[name] = {"type": "primitive", "value": value}
        else:
            raise CleanRoomSerializationError(
                f"Cannot serialize parameter '{name}' of type {type(value).__name__}"
            )

    return CleanRoomBundle(manifest=manifest, dataframes=dataframes)


def deserialize_params(manifest: dict, dataframes: Dict[str, bytes]) -> Dict[str, Any]:
    """\
    Deserialize parameters from a manifest and DataFrame bytes.

    :param manifest: the JSON manifest dict
    :param dataframes: dict mapping param name to Parquet bytes
    :return: dictionary of parameter names to values
    """
    params = {}
    for name, entry in manifest.items():
        if entry["type"] == "primitive":
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

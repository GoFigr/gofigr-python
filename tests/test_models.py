import json
from pathlib import Path

import numpy as np
import pandas as pd

from gofigr.models import DataType

from tests.test_client import DATA_DIR


def _strip_fields(json_data):
    for name in ['local_id', 'size_bytes']:
        if 'metadata' in json_data and name in json_data['metadata']:
            del json_data['metadata'][name]
        elif name in json_data:
            del json_data[name]
    return json_data


class TestMixins:
    def test_metadata_defaults(self, mock_gf):
        """\
        Tests that we include metadata defaults even if not directly supplied.
        """
        img = mock_gf.ImageData(data=bytes([1, 2, 3]))

        assert _strip_fields(img.to_json(include_none=True)) == {
            'api_id': None,
            'name': None,
            'hash': None,
            'is_clean_room': False,
            'type': 'image',
            'metadata': {'is_watermarked': False, 'format': None},
            'data': 'AQID',
        }

        assert mock_gf.ImageData.from_json(img.to_json()).to_json() == img.to_json()
        assert img.name is None
        assert img.type == DataType.IMAGE
        assert img.is_watermarked is False
        assert img.format is None

    def test_metadata_customs(self, mock_gf):
        """\
        Tests that we can override metadata defaults.
        """
        img = mock_gf.ImageData(name="test image", data=bytes([1, 2, 3]), is_watermarked=True, format="png")

        assert _strip_fields(img.to_json(include_none=True)) == {
            'api_id': None,
            'name': 'test image',
            'hash': None,
            'is_clean_room': False,
            'type': 'image',
            'metadata': {'is_watermarked': True, 'format': 'png'},
            'data': 'AQID',
        }

        assert mock_gf.ImageData.from_json(img.to_json()).to_json() == img.to_json()
        assert img.name == 'test image'
        assert img.type == DataType.IMAGE
        assert img.is_watermarked is True
        assert img.format == 'png'

    def test_metadata_overrides(self, mock_gf):
        """\
        Tests that metadata fields supplied as keyword arguments take precedence over those supplied in the
        metadata dictionary.
        """
        img = mock_gf.ImageData(name="test image", data=bytes([1, 2, 3]),
                                metadata={'is_watermarked': False, 'format': "eps"},
                                is_watermarked=True, format="png")

        assert _strip_fields(img.to_json(include_none=True)) == {
            'api_id': None,
            'name': 'test image',
            'hash': None,
            'is_clean_room': False,
            'type': 'image',
            'metadata': {'is_watermarked': True, 'format': 'png'},
            'data': 'AQID',
        }

        assert mock_gf.ImageData.from_json(img.to_json()).to_json() == img.to_json()
        assert img.name == 'test image'
        assert img.type == DataType.IMAGE
        assert img.is_watermarked is True
        assert img.format == 'png'


class TestTextDataFormat:
    def test_format_default_none(self, mock_gf):
        txt = mock_gf.TextData(contents="hello")
        assert txt.format is None

    def test_format_json(self, mock_gf):
        txt = mock_gf.TextData(contents='{"key": "value"}', format="json")
        assert txt.format == "json"
        assert txt.contents == '{"key": "value"}'

    def test_format_json_roundtrip(self, mock_gf):
        txt = mock_gf.TextData(contents="test", format="json")
        restored = mock_gf.TextData.from_json(txt.to_json())
        assert restored.format == "json"
        assert restored.contents == "test"


class TestTableDataParquet:
    def test_csv_default(self, mock_gf):
        df = pd.DataFrame({"a": [1, 2, 3]})
        td = mock_gf.TableData(name="test", dataframe=df)
        assert td.format == "csv"
        assert td.dataframe.equals(df)

    def test_parquet_format(self, mock_gf):
        df = pd.DataFrame({"a": [1, 2, 3], "b": [4.0, 5.0, 6.0]})
        td = mock_gf.TableData(name="test", dataframe=df, format="parquet")
        assert td.format == "parquet"
        assert td.dataframe.equals(df)

    def test_parquet_preserves_dtypes(self, mock_gf):
        df = pd.DataFrame({
            "ints": pd.array([1, 2, 3], dtype="int64"),
            "floats": pd.array([1.0, 2.0, 3.0], dtype="float64"),
            "bools": pd.array([True, False, True], dtype="bool"),
        })
        td = mock_gf.TableData(name="test", dataframe=df, format="parquet")
        restored = td.dataframe
        for col in df.columns:
            assert restored[col].dtype == df[col].dtype

    def test_parquet_roundtrip_via_json(self, mock_gf):
        df = pd.DataFrame({"x": np.arange(50)})
        td = mock_gf.TableData(name="test", dataframe=df, format="parquet")
        restored = mock_gf.TableData.from_json(td.to_json())
        assert restored.format == "parquet"
        assert restored.dataframe.equals(df)

    def test_none_dataframe(self, mock_gf):
        td = mock_gf.TableData(name="test", format="parquet")
        assert td.dataframe is None


class TestIsCleanRoomField:
    def test_data_default_false(self, mock_gf):
        data = mock_gf.Data(data=bytes([1, 2, 3]))
        assert data.is_clean_room is False

    def test_data_set_true(self, mock_gf):
        data = mock_gf.CodeData(contents="print('hi')", is_clean_room=True)
        assert data.is_clean_room is True

    def test_data_json_roundtrip(self, mock_gf):
        code = mock_gf.CodeData(contents="x = 1", is_clean_room=True)
        json_data = code.to_json()
        assert json_data.get("is_clean_room") is True

        restored = mock_gf.CodeData.from_json(json_data)
        assert restored.is_clean_room is True

    def test_data_default_in_json(self, mock_gf):
        code = mock_gf.CodeData(contents="x = 1")
        json_data = code.to_json()
        assert json_data.get("is_clean_room") is False


class TestFileDataRead:
    def test_pathlib_path_converted_to_str(self, mock_gf):
        """FileData.read() should accept pathlib.Path and store path as str."""
        path = DATA_DIR / 'blob.bin'
        data_obj = mock_gf.FileData.read(path)

        assert isinstance(data_obj.path, str)
        assert data_obj.path == str(path)
        # to_json must produce JSON-serializable output
        json.dumps(data_obj.to_json())

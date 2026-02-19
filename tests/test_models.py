import unittest

import numpy as np
import pandas as pd

from gofigr.models import DataType

from tests.test_client import make_gf


def _strip_fields(json_data):
    for name in ['local_id', 'size_bytes']:
        if 'metadata' in json_data and name in json_data['metadata']:
            del json_data['metadata'][name]
        elif name in json_data:
            del json_data[name]
    return json_data


class TestMixins(unittest.TestCase):
    def test_metadata_defaults(self):
        """\
        Tests that we include metadata defaults even if not directly supplied.
        """
        gf = make_gf()
        img = gf.ImageData(data=bytes([1, 2, 3]))

        self.assertEqual(_strip_fields(img.to_json(include_none=True)),
                         {'api_id': None,
                          'name': None,
                          'hash': None,
                          'type': 'image',
                          'metadata': {'is_watermarked': False, 'format': None},  # metadata defaults should be present
                          'data': 'AQID'})

        self.assertEqual(gf.ImageData.from_json(img.to_json()).to_json(), img.to_json())  # JSON roundtrip
        self.assertEqual(img.name, None)
        self.assertEqual(img.type, DataType.IMAGE)
        self.assertEqual(img.is_watermarked, False)
        self.assertEqual(img.format, None)

    def test_metadata_customs(self):
        """\
        Tests that we can override metadata defaults.
        """
        gf = make_gf()
        img = gf.ImageData(name="test image", data=bytes([1, 2, 3]), is_watermarked=True, format="png")

        self.assertEqual(_strip_fields(img.to_json(include_none=True)),
                         {'api_id': None,
                         'name': 'test image',
                          'hash': None,
                          'type': 'image',
                          'metadata': {'is_watermarked': True, 'format': 'png'},
                          'data': 'AQID'})

        self.assertEqual(gf.ImageData.from_json(img.to_json()).to_json(), img.to_json())
        self.assertEqual(img.name, 'test image')
        self.assertEqual(img.type, DataType.IMAGE)
        self.assertEqual(img.is_watermarked, True)
        self.assertEqual(img.format, 'png')

    def test_metadata_overrides(self):
        """\
        Tests that metadata fields supplied as keyword arguments take precedence over those supplied in the
        metadata dictionary.
        """
        gf = make_gf()
        img = gf.ImageData(name="test image", data=bytes([1, 2, 3]),
                           metadata={'is_watermarked': False, 'format': "eps"},
                           is_watermarked=True, format="png")

        self.assertEqual(_strip_fields(img.to_json(include_none=True)),
                         {'api_id': None,
                          'name': 'test image',
                          'hash': None,
                          'type': 'image',
                          'metadata': {'is_watermarked': True, 'format': 'png'},
                          'data': 'AQID'})

        self.assertEqual(gf.ImageData.from_json(img.to_json()).to_json(), img.to_json())  # JSON roundtrip
        self.assertEqual(img.name, 'test image')
        self.assertEqual(img.type, DataType.IMAGE)
        self.assertEqual(img.is_watermarked, True)
        self.assertEqual(img.format, 'png')


class TestTextDataFormat(unittest.TestCase):
    def test_format_default_none(self):
        gf = make_gf()
        txt = gf.TextData(contents="hello")
        self.assertIsNone(txt.format)

    def test_format_json(self):
        gf = make_gf()
        txt = gf.TextData(contents='{"key": "value"}', format="json")
        self.assertEqual(txt.format, "json")
        self.assertEqual(txt.contents, '{"key": "value"}')

    def test_format_json_roundtrip(self):
        gf = make_gf()
        txt = gf.TextData(contents="test", format="json")
        restored = gf.TextData.from_json(txt.to_json())
        self.assertEqual(restored.format, "json")
        self.assertEqual(restored.contents, "test")


class TestTableDataParquet(unittest.TestCase):
    def test_csv_default(self):
        gf = make_gf()
        df = pd.DataFrame({"a": [1, 2, 3]})
        td = gf.TableData(name="test", dataframe=df)
        self.assertEqual(td.format, "pandas/csv")
        self.assertTrue(td.dataframe.equals(df))

    def test_parquet_format(self):
        gf = make_gf()
        df = pd.DataFrame({"a": [1, 2, 3], "b": [4.0, 5.0, 6.0]})
        td = gf.TableData(name="test", dataframe=df, format="pandas/parquet")
        self.assertEqual(td.format, "pandas/parquet")
        self.assertTrue(td.dataframe.equals(df))

    def test_parquet_preserves_dtypes(self):
        gf = make_gf()
        df = pd.DataFrame({
            "ints": pd.array([1, 2, 3], dtype="int64"),
            "floats": pd.array([1.0, 2.0, 3.0], dtype="float64"),
            "bools": pd.array([True, False, True], dtype="bool"),
        })
        td = gf.TableData(name="test", dataframe=df, format="pandas/parquet")
        restored = td.dataframe
        for col in df.columns:
            self.assertEqual(restored[col].dtype, df[col].dtype)

    def test_parquet_roundtrip_via_json(self):
        gf = make_gf()
        df = pd.DataFrame({"x": np.arange(50)})
        td = gf.TableData(name="test", dataframe=df, format="pandas/parquet")
        restored = gf.TableData.from_json(td.to_json())
        self.assertEqual(restored.format, "pandas/parquet")
        self.assertTrue(restored.dataframe.equals(df))

    def test_none_dataframe(self):
        gf = make_gf()
        td = gf.TableData(name="test", format="pandas/parquet")
        self.assertIsNone(td.dataframe)


class TestIsCleanRoomField(unittest.TestCase):
    def test_data_default_false(self):
        gf = make_gf()
        data = gf.Data(data=bytes([1, 2, 3]))
        self.assertFalse(data.is_clean_room)

    def test_data_set_true(self):
        gf = make_gf()
        data = gf.CodeData(contents="print('hi')", is_clean_room=True)
        self.assertTrue(data.is_clean_room)

    def test_data_json_roundtrip(self):
        gf = make_gf()
        code = gf.CodeData(contents="x = 1", is_clean_room=True)
        json_data = code.to_json()
        self.assertTrue(json_data.get("is_clean_room"))

        restored = gf.CodeData.from_json(json_data)
        self.assertTrue(restored.is_clean_room)

    def test_data_default_in_json(self):
        gf = make_gf()
        code = gf.CodeData(contents="x = 1")
        json_data = code.to_json()
        self.assertFalse(json_data.get("is_clean_room"))

import unittest

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

        self.assertEqual(gf.ImageData.from_json(img.to_json()).to_json(), img.to_json())  # JSON roundtrip
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

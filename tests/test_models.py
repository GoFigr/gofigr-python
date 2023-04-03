import unittest

from gofigr import ImageData, DataType


class TestMixins(unittest.TestCase):
    def test_metadata_defaults(self):
        """\
        Tests that we include metadata defaults even if not directly supplied.
        """
        img = ImageData(data=bytes([1, 2, 3]))

        self.assertEqual(img.to_json(),
                         {'api_id': None,
                          'name': None,
                          'type': 'image',
                          'metadata': {'is_watermarked': False, 'format': None},  # metadata defaults should be present
                          'data': 'AQID'})

        self.assertEqual(ImageData.from_json(img.to_json()).to_json(), img.to_json())  # JSON roundtrip
        self.assertEqual(img.name, None)
        self.assertEqual(img.type, DataType.IMAGE)
        self.assertEqual(img.is_watermarked, False)
        self.assertEqual(img.format, None)

    def test_metadata_customs(self):
        """\
        Tests that we can override metadata defaults.
        """
        img = ImageData(name="test image", data=bytes([1, 2, 3]), is_watermarked=True, format="png")

        self.assertEqual(img.to_json(),
                         {'api_id': None,
                         'name': 'test image',
                          'type': 'image',
                          'metadata': {'is_watermarked': True, 'format': 'png'},
                          'data': 'AQID'})

        self.assertEqual(ImageData.from_json(img.to_json()).to_json(), img.to_json())  # JSON roundtrip
        self.assertEqual(img.name, 'test image')
        self.assertEqual(img.type, DataType.IMAGE)
        self.assertEqual(img.is_watermarked, True)
        self.assertEqual(img.format, 'png')

    def test_metadata_overrides(self):
        """\
        Tests that metadata fields supplied as keyword arguments take precedence over those supplied in the
        metadata dictionary.
        """
        img = ImageData(name="test image", data=bytes([1, 2, 3]), metadata={'is_watermarked': False, 'format': "eps"},
                        is_watermarked=True, format="png")

        self.assertEqual(img.to_json(),
                         {'api_id': None,
                          'name': 'test image',
                          'type': 'image',
                          'metadata': {'is_watermarked': True, 'format': 'png'},
                          'data': 'AQID'})

        self.assertEqual(ImageData.from_json(img.to_json()).to_json(), img.to_json())  # JSON roundtrip
        self.assertEqual(img.name, 'test image')
        self.assertEqual(img.type, DataType.IMAGE)
        self.assertEqual(img.is_watermarked, True)
        self.assertEqual(img.format, 'png')

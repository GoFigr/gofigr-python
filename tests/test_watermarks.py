"""\
Copyright (c) 2022, Flagstaff Solutions, LLC
All rights reserved.

"""
import PIL
from pathlib import Path

from gofigr.watermarks import DefaultWatermark

DATA_DIR = Path(__file__).parent / "data"


class TestQRWatermark:
    def test_qr_watermark(self, mock_gf):
        rev = mock_gf.Revision(api_id="7372fc16-ee27-4293-b6ba-5c15f7e5d3c2")

        qrw = DefaultWatermark()

        for image_format in ['png', 'eps']:  # PIL doesn't support svg, yet
            with open(DATA_DIR / f'plot.{image_format}', 'rb') as f:
                fig_image = PIL.Image.open(f)
                fig_image.load()

            watermarked_img = qrw.apply(fig_image, rev)

            # Not much we can test without visual inspection
            assert watermarked_img is not None
            assert watermarked_img.width >= fig_image.width
            assert watermarked_img.height >= fig_image.height

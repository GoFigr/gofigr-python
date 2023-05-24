"""\
Copyright (c) 2022, Flagstaff Solutions, LLC
All rights reserved.

"""
import io

import pkg_resources
import pyqrcode
from PIL import Image, ImageDraw, ImageFont

from gofigr import APP_URL


class Watermark:
    """\
    Base class for drawing watermaks on figures.

    """
    def apply(self, image, revision):
        """\
        Places a watermark on an image

        :param image: PIL Image object
        :param revision: GoFigr revision object
        """
        raise NotImplementedError()


def _qr_to_image(text, **kwargs):
    """Creates a QR code for the text, and returns it as a PIL.Image"""
    qr = pyqrcode.create(text)
    bio = io.BytesIO()
    qr.png(bio, **kwargs)
    bio.seek(0)

    image = Image.open(bio)
    image.load()
    return image


def _default_font():
    """Loads the default font and returns it as an ImageFont"""
    return ImageFont.truetype(pkg_resources.resource_filename("gofigr.resources", "FreeMono.ttf"), 14)


class DefaultWatermark:
    """\
    Draws QR codes + URL watermark on figures.

    """
    def __init__(self,
                 show_qr_code=False,
                 margin_px=10,
                 qr_background=(0x00, 0x00, 0x00, 0x00),
                 qr_foreground=(0x00, 0x00, 0x00, 0x99),
                 qr_scale=2, font=None):
        """

        :param show_qr_code: whether to show the QR code. Default is False
        :param margin_px: margin for the QR code, in pixels
        :param qr_background: RGBA tuple for QR background color
        :param qr_foreground: RGBA tuple for QR foreground color
        :param qr_scale: QR scale, as an integer
        :param font: font for the identifier
        """
        self.margin_px = margin_px
        self.qr_background = qr_background
        self.qr_foreground = qr_foreground
        self.qr_scale = qr_scale
        self.font = font if font is not None else _default_font()
        self.show_qr_code = show_qr_code

    def apply(self, image, revision):
        """\
        Adds a QR watermark to an image.

        :param image: PIL.Image
        :param revision: instance of FigureRevision
        :return: PIL.Image containing the watermarked image

        """
        identifier = f'GoFigr: {revision.api_id}' if self.show_qr_code else f'{APP_URL}/r/{revision.api_id}'

        left, top, right, bottom = self.font.getbbox(identifier)
        text_height = bottom - top
        text_width = right - left

        res_img = Image.new(mode="RGBA", size=(image.width, image.height + (bottom - top) + self.margin_px * 2))

        draw = ImageDraw.Draw(res_img)
        draw.text(((res_img.width - text_width) / 2, res_img.height - text_height - self.margin_px),
                  identifier, fill="black", font=self.font)

        res_img.paste(image, (0, 0))

        if self.show_qr_code:
            qr_img = _qr_to_image(f'{APP_URL}/r/{revision.api_id}', scale=self.qr_scale,
                                  module_color=self.qr_foreground,
                                  background=self.qr_background)

            res_img.paste(qr_img, (res_img.width - qr_img.width, res_img.height - qr_img.height))

        return res_img

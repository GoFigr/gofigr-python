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


def stack_horizontally(*images, alignment="center"):
    """
    Stacks images horizontally. Thanks, Stack Overflow!

    https://stackoverflow.com/questions/30227466/combine-several-images-horizontally-with-python

    """
    images = [im for im in images if im is not None]
    widths, heights = zip(*(i.size for i in images))

    total_width = sum(widths)
    max_height = max(heights)

    res = Image.new('RGBA', (total_width, max_height))
    x_offset = 0
    for im in images:
        if alignment == "center":
            res.paste(im, (x_offset, (max_height - im.size[1]) // 2))
        elif alignment == "top":
            res.paste(im, (x_offset, 0))
        elif alignment == "bottom":
            res.paste(im, (x_offset, max_height - im.size[1]))
        else:
            raise ValueError(alignment)

        x_offset += im.size[0]

    return res


def stack_vertically(*images, alignment="center"):
    """Stacks images vertically."""
    images = [im for im in images if im is not None]
    widths, heights = zip(*(i.size for i in images))

    total_height = sum(heights)
    max_width = max(widths)

    res = Image.new('RGBA', (max_width, total_height))
    y_offset = 0
    for im in images:
        if alignment == "center":
            res.paste(im, ((max_width - im.size[0]) // 2, y_offset))
        elif alignment == "left":
            res.paste(im, (0, y_offset))
        elif alignment == "right":
            res.paste(im, (max_width - im.size[0], y_offset))
        else:
            raise ValueError(alignment)

        y_offset += im.size[1]

    return res


def add_margins(img, margins):
    """Adds margins to an image"""
    res = Image.new('RGBA', (img.size[0] + margins[0] * 2,
                             img.size[1] + margins[1] * 2))

    res.paste(img, (margins[0], margins[1]))
    return res


class DefaultWatermark:
    """\
    Draws QR codes + URL watermark on figures.

    """
    def __init__(self,
                 show_qr_code=True,
                 margin_px=10,
                 qr_background=(0x00, 0x00, 0x00, 0x00),
                 qr_foreground=(0x00, 0x00, 0x00, 0x99),
                 qr_scale=2, font=None):
        """

        :param show_qr_code: whether to show the QR code. Default is True
        :param margin_px: margin as an x, y tuple
        :param qr_background: RGBA tuple for QR background color
        :param qr_foreground: RGBA tuple for QR foreground color
        :param qr_scale: QR scale, as an integer
        :param font: font for the identifier
        """
        self.margin_px = margin_px
        if not hasattr(self.margin_px, '__iter__'):
            self.margin_px = (self.margin_px, self.margin_px)

        self.qr_background = qr_background
        self.qr_foreground = qr_foreground
        self.qr_scale = qr_scale
        self.font = font if font is not None else _default_font()
        self.show_qr_code = show_qr_code

    def draw_identifier(self, text):
        """Draws the GoFigr identifier text, returning it as a PIL image"""
        left, top, right, bottom = self.font.getbbox(text)
        text_height = bottom - top
        text_width = right - left

        img = Image.new(mode="RGBA", size=(text_width + 2 * self.margin_px[0], text_height + 2 * self.margin_px[1]))
        draw = ImageDraw.Draw(img)
        draw.text((self.margin_px[0], self.margin_px[1]), text, fill="black", font=self.font)
        return img

    def get_watermark(self, revision):
        """\
        Generates just the watermark for a revision.

        :param revision: FigureRevision
        :return: PIL.Image

        """
        identifier_text = f'{APP_URL}/r/{revision.api_id}'
        identifier_img = self.draw_identifier(identifier_text)

        qr_img = None
        if self.show_qr_code:
            qr_img = _qr_to_image(f'{APP_URL}/r/{revision.api_id}', scale=self.qr_scale,
                                  module_color=self.qr_foreground,
                                  background=self.qr_background)
            qr_img = add_margins(qr_img, self.margin_px)

        return stack_horizontally(identifier_img, qr_img)

    def apply(self, image, revision):
        """\
        Adds a QR watermark to an image.

        :param image: PIL.Image
        :param revision: instance of FigureRevision
        :return: PIL.Image containing the watermarked image

        """
        return stack_vertically(image, self.get_watermark(revision))

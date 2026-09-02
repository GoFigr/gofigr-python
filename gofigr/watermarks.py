"""\
Copyright (c) 2022, Flagstaff Solutions, LLC
All rights reserved.

"""
import inspect
import io

import qrcode
from qrcode.image.styledpil import StyledPilImage
from qrcode.image.styles.moduledrawers.pil import RoundedModuleDrawer
from PIL import Image, ImageDraw, ImageFont

from gofigr.compat import open_resource_binary
from gofigr.utils import read_resource_binary

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


_RENDER_BOX_SIZE = 20  # render at high resolution for crisp rounded modules
_LOGO_FRACTION = 0.25  # logo covers up to 25% of QR width

# The watermark strip was designed against ~800px-wide figures (the default
# 8in x 100dpi render). On high-dpi/retina publishes the image is 2-3x that,
# and a fixed 14px font + tiny QR become unreadable — so the strip scales
# with image width, relative to this reference, capped to stay sane on
# posters.
REFERENCE_IMAGE_WIDTH_PX = 800
MAX_WATERMARK_SCALE = 4.0


_RESAMPLE = getattr(Image, 'Resampling', Image).LANCZOS


def _load_logo():
    """Load the GoFigr logo as a PIL RGBA image."""
    logo_bytes = read_resource_binary("gofigr.resources", "logo_small.png")
    logo = Image.open(io.BytesIO(logo_bytes))
    logo.load()
    return logo.convert("RGBA")


def _embed_logo(img):
    """Embed the GoFigr logo in the center of *img*, flattened onto white."""
    logo = _load_logo()
    logo_size = int(img.width * _LOGO_FRACTION)
    logo = logo.resize((logo_size, logo_size), _RESAMPLE)
    logo_bg = Image.new("RGBA", logo.size, (255, 255, 255, 255))
    logo_bg.paste(logo, mask=logo)
    offset = ((img.width - logo_size) // 2, (img.height - logo_size) // 2)
    img.paste(logo_bg, offset)


def _qr_to_image(text, box_size=2, border=1,
                  fill_color=(0, 0, 0, 0x99),
                  back_color=(0, 0, 0, 0),
                  module_drawer=None,
                  embed_logo=True):
    """Creates a QR code for the text, and returns it as a PIL.Image"""
    qr = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_H if embed_logo else qrcode.constants.ERROR_CORRECT_M,
        box_size=_RENDER_BOX_SIZE,
        border=border,
    )
    qr.add_data(text)
    qr.make(fit=True)

    if module_drawer is None:
        module_drawer = RoundedModuleDrawer(radius_ratio=0.5)

    img = qr.make_image(
        image_factory=StyledPilImage,
        module_drawer=module_drawer,
    )

    # StyledPilImage renders black/white RGB; convert to RGBA and apply colors
    img = img.convert("RGBA")
    get_pixels = getattr(img, 'get_flattened_data', None) or img.getdata
    img.putdata([fill_color if px[:3] == (0, 0, 0) else back_color for px in get_pixels()])

    if embed_logo:
        _embed_logo(img)

    # Downscale to the requested box_size
    if box_size != _RENDER_BOX_SIZE:
        target = (qr.modules_count + 2 * border) * box_size
        img = img.resize((target, target), _RESAMPLE)

    return img


def _default_font():
    """Loads the default font and returns it as an ImageFont"""
    with open_resource_binary("gofigr.resources", "FreeMono.ttf") as f:
        return ImageFont.truetype(f, 14)


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
                 qr_background=(0xFF, 0xFF, 0xFF, 0xFF),
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

    def draw_table(self, pairs, padding_x=10, padding_y=10, border_width=1):
        """Draws key-value pairs as a table, returning it as a PIL image."""
        # pylint: disable=too-many-locals

        # Calculate column widths and row height
        key_col_width = 0
        val_col_width = 0
        row_height = 0

        for key, value in pairs:
            # Get bounding boxes for text
            key_bbox = self.font.getbbox(key)
            val_bbox = self.font.getbbox(value)

            key_col_width = max(key_col_width, key_bbox[2] - key_bbox[0])
            val_col_width = max(val_col_width, val_bbox[2] - val_bbox[0])
            row_height = max(row_height, key_bbox[3] - key_bbox[1], val_bbox[3] - val_bbox[1])

        # Add padding and border space
        total_width = key_col_width + val_col_width + 3 * padding_x + border_width
        total_height = (row_height + padding_y) * len(pairs) + border_width

        # Create the new image
        img = Image.new(mode="RGBA", size=(total_width, total_height))
        draw = ImageDraw.Draw(img)

        # Draw the text and horizontal lines
        y_pos = border_width
        for idx, (key, value) in enumerate(pairs):
            draw.text((padding_x, y_pos), key, fill="black", font=self.font)
            draw.text((key_col_width + 2 * padding_x, y_pos), value, fill="black", font=self.font)
            y_pos += row_height + padding_y

            # Draw horizontal lines
            if idx < len(pairs) - 1:
                draw.line([(0, y_pos - padding_y / 2), (total_width, y_pos - padding_y / 2)],
                          fill="black", width=border_width)

        # Draw the vertical line separating columns
        draw.line([(key_col_width + padding_x, 0), (key_col_width + padding_x, total_height)], fill="black",
                  width=border_width)

        return img

    @staticmethod
    def image_scale(image_width):
        """Watermark scale factor for an image of the given pixel width."""
        return min(MAX_WATERMARK_SCALE,
                   max(1.0, image_width / REFERENCE_IMAGE_WIDTH_PX))

    def _scaled_font(self, scale):
        if scale == 1 or not hasattr(self.font, 'font_variant'):
            return self.font
        return self.font.font_variant(size=round(self.font.size * scale))

    def _scaled_margins(self, scale):
        return (round(self.margin_px[0] * scale), round(self.margin_px[1] * scale))

    def draw_identifier(self, text, scale=1):
        """Draws the GoFigr identifier text, returning it as a PIL image"""
        font = self._scaled_font(scale)
        margin_x, margin_y = self._scaled_margins(scale)
        left, top, right, bottom = font.getbbox(text)
        text_height = bottom - top
        text_width = right - left

        img = Image.new(mode="RGBA", size=(text_width + 2 * margin_x, text_height + 2 * margin_y))
        draw = ImageDraw.Draw(img)
        draw.text((margin_x, margin_y), text, fill="black", font=font)
        return img

    def _build_watermark_strip(self, url_text, scale=1):
        """Build the watermark strip image for a given URL string.

        :param url_text: full URL to encode in the watermark
        :param scale: scale factor relative to the reference image width
        :return: PIL.Image of the watermark strip (text + optional QR code)
        """
        identifier_img = self.draw_identifier(url_text, scale=scale)

        qr_img = None
        if self.show_qr_code:
            qr_img = _qr_to_image(url_text, box_size=max(1, round(self.qr_scale * scale)),
                                  fill_color=self.qr_foreground,
                                  back_color=self.qr_background)
            qr_img = add_margins(qr_img, self._scaled_margins(scale))

        return stack_horizontally(identifier_img, qr_img)

    def get_watermark(self, revision, scale=1):
        """\
        Generates just the watermark for a revision.

        :param revision: FigureRevision
        :param scale: scale factor relative to the reference image width
        :return: PIL.Image

        """
        # Use short_id for a more compact QR code when available
        url_id = getattr(revision, '_short_id', None) or revision.api_id
        return self._build_watermark_strip(f'{APP_URL}/r/{url_id}', scale=scale)

    def _get_watermark_size(self, scale=1):
        """Return the (width, height) of the watermark strip at a scale.

        The size is constant for UUID-based URLs, so it is computed once
        per scale with a dummy UUID and cached for subsequent calls.
        """
        if not hasattr(self, '_cached_wm_sizes'):
            self._cached_wm_sizes = {}  # pylint: disable=attribute-defined-outside-init
        if scale not in self._cached_wm_sizes:
            dummy_url = f'{APP_URL}/r/12345678AB'
            self._cached_wm_sizes[scale] = self._build_watermark_strip(dummy_url, scale=scale).size
        return self._cached_wm_sizes[scale]

    def get_watermark_height(self, image_width=REFERENCE_IMAGE_WIDTH_PX):
        """Return the pixel height of the watermark strip for an image of
        the given width."""
        return self._get_watermark_size(self.image_scale(image_width))[1]

    def pad_for_watermark(self, image):
        """Add blank vertical space below the image matching the watermark
        height.  Only pads height, not width, so the preview matches the
        published image size regardless of watermark URL length.
        """
        _, wm_h = self._get_watermark_size(self.image_scale(image.width))
        padded = Image.new('RGBA', (image.width, image.height + wm_h),
                           (255, 255, 255, 255))
        padded.paste(image, (0, 0))
        return padded

    def apply(self, image, revision):
        """\
        Adds a QR watermark to an image.

        :param image: PIL.Image
        :param revision: instance of FigureRevision
        :return: PIL.Image containing the watermarked image

        """
        # Subclasses (e.g. gofigr.lite) may override get_watermark without
        # the scale parameter — fall back to unscaled for those.
        if 'scale' in inspect.signature(self.get_watermark).parameters:
            watermark = self.get_watermark(revision, scale=self.image_scale(image.width))
        else:
            watermark = self.get_watermark(revision)
        return stack_vertically(image, watermark)

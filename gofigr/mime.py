"""\
Copyright (c) 2026, Flagstaff Solutions, LLC
All rights reserved.

A GoFigr-specific MIME representation of a published figure, emitted next
to the usual image/png and text/html so a GoFigr-aware frontend (the
GoFigr canvas) can render the figure itself: draw the watermark, offer
copy/download with or without it, and show the "published" widget as a
native component. Frontends that don't know the type ignore it and fall
back to the HTML/PNG as before.
"""
import json
from base64 import b64encode

GOFIGR_FIGURE_MIME = "application/vnd.gofigr.figure+json"
PAYLOAD_VERSION = 1

# Keep the embedded raw image bounded: the canvas stores run outputs with a
# 2 MB cap on base64 images; anything bigger is referenced, not embedded.
MAX_EMBEDDED_IMAGE_BYTES = 1_400_000


def _iso(dt):
    try:
        return dt.isoformat()
    except AttributeError:
        return None


def _figure_fields(rev):
    fig = getattr(rev, 'figure', None)
    if fig is None:
        return {"api_id": None, "name": None}
    return {"api_id": str(getattr(fig, 'api_id', '') or '') or None,
            "name": getattr(fig, 'name', None) or None}


def build_figure_payload(rev, raw_png=None, watermark=None, interactive=None, image_size=None):
    """\
    Build the JSON payload for GOFIGR_FIGURE_MIME.

    :param rev: the published gf.Revision (after create: api_id and URL known)
    :param raw_png: bytes of the UNWATERMARKED PNG (the frontend draws the
        watermark itself), or None
    :param watermark: the DefaultWatermark used (for the strip's parameters)
    :param interactive: {"kind": "plotly", "figure": {...}} for interactive
        figures, else None
    :param image_size: (width, height) of the raw PNG in pixels
    :return: dict
    """
    url = None
    try:
        url = rev.revision_url
    except AttributeError:
        pass
    short_id = getattr(rev, '_short_id', None)
    formats = []
    for data in (getattr(rev, 'image_data', None) or []):
        fmt = getattr(data, 'format', None)
        if fmt:
            formats.append({"format": str(fmt).lower(), "watermarked": bool(getattr(data, 'is_watermarked', False))})

    image = None
    if raw_png is not None:
        embedded = len(raw_png) <= MAX_EMBEDDED_IMAGE_BYTES
        image = {
            "format": "png",
            "width": image_size[0] if image_size else None,
            "height": image_size[1] if image_size else None,
            "b64": b64encode(raw_png).decode('ascii') if embedded else None,
            "embedded": embedded,
        }

    wm = None
    if watermark is not None:
        wm = {
            "url": url,
            "qr": bool(getattr(watermark, 'show_qr_code', True)),
            "margin_px": list(getattr(watermark, 'margin_px', (10, 10))),
            "qr_scale": getattr(watermark, 'qr_scale', 2),
            "font_px": getattr(getattr(watermark, 'font', None), 'size', 14),
        }

    return {
        "version": PAYLOAD_VERSION,
        "revision": {
            "api_id": str(getattr(rev, 'api_id', '') or '') or None,
            "short_id": short_id,
            "url": url,
            "created_on": _iso(getattr(rev, 'created_on', None)),
            "size_bytes": getattr(rev, 'size_bytes', None),
        },
        "figure": _figure_fields(rev),
        "watermark": wm,
        "image": image,
        "interactive": interactive,
        "formats": formats,
    }


def payload_to_json(payload):
    """JSON text for the bundle (the kernel sends JSON MIME types as objects,
    but a string is accepted everywhere and survives nbformat round trips)."""
    return json.dumps(payload)

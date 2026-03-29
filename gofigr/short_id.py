"""
Short ID utilities for compact figure revision identifiers.

Mirrors the server-side implementation in gofigr_server/portal/short_id.py.
"""
import string

BASE62_CHARS = string.digits + string.ascii_lowercase + string.ascii_uppercase


def base62_encode(num):
    """Encode a non-negative integer as a base62 string."""
    if num < 0:
        raise ValueError("Cannot encode negative numbers")
    if num == 0:
        return '0'

    chars = []
    while num > 0:
        num, remainder = divmod(num, 62)
        chars.append(BASE62_CHARS[remainder])
    return ''.join(reversed(chars))


def make_short_id(prefix, index):
    """Combine a prefix with a base62-encoded index to form a short ID."""
    return prefix + base62_encode(index)

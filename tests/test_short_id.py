"""Tests for short ID utilities (base62 encoding and make_short_id)."""
import unittest

from gofigr.short_id import base62_encode, make_short_id, BASE62_CHARS


class TestBase62Encode(unittest.TestCase):
    """Unit tests for base62_encode."""

    def test_zero(self):
        self.assertEqual(base62_encode(0), '0')

    def test_single_digit_values(self):
        """0-9 map to '0'-'9', 10-35 to 'a'-'z', 36-61 to 'A'-'Z'."""
        self.assertEqual(base62_encode(1), '1')
        self.assertEqual(base62_encode(9), '9')
        self.assertEqual(base62_encode(10), 'a')
        self.assertEqual(base62_encode(35), 'z')
        self.assertEqual(base62_encode(36), 'A')
        self.assertEqual(base62_encode(61), 'Z')

    def test_boundaries(self):
        """62 = '10', 62^2 = '100', etc."""
        self.assertEqual(base62_encode(62), '10')
        self.assertEqual(base62_encode(63), '11')
        self.assertEqual(base62_encode(3844), '100')

    def test_large_values(self):
        """Encoding large values produces only base62 characters."""
        for n in [10**6, 10**12, 10**18, 2**64]:
            encoded = base62_encode(n)
            self.assertTrue(all(c in BASE62_CHARS for c in encoded),
                            f"Non-base62 char in encoding of {n}: {encoded}")
            self.assertGreater(len(encoded), 0)

    def test_negative_raises(self):
        with self.assertRaises(ValueError):
            base62_encode(-1)

    def test_monotonic(self):
        """Larger inputs produce lexicographically later or longer strings."""
        for a, b in [(0, 1), (9, 10), (61, 62), (100, 1000)]:
            ea, eb = base62_encode(a), base62_encode(b)
            self.assertTrue(
                len(eb) > len(ea) or (len(eb) == len(ea) and eb > ea),
                f"base62_encode({a})={ea!r} not < base62_encode({b})={eb!r}"
            )

    def test_no_leading_zeros(self):
        """Encodings of positive numbers should not have leading zeros."""
        for n in [1, 10, 62, 100, 3844, 10**6]:
            encoded = base62_encode(n)
            self.assertNotEqual(encoded[0], '0',
                                f"Leading zero in base62_encode({n})={encoded!r}")

    def test_output_is_str(self):
        self.assertIsInstance(base62_encode(0), str)
        self.assertIsInstance(base62_encode(999), str)

    def test_all_single_chars_reachable(self):
        """Every base62 character is reachable as a single-character encoding."""
        single_chars = {base62_encode(i) for i in range(62)}
        self.assertEqual(single_chars, set(BASE62_CHARS))

    def test_sequential_uniqueness(self):
        """First 10000 encodings are all unique."""
        encodings = [base62_encode(i) for i in range(10000)]
        self.assertEqual(len(encodings), len(set(encodings)))


class TestMakeShortId(unittest.TestCase):
    """Unit tests for make_short_id."""

    def test_basic(self):
        self.assertEqual(make_short_id('xK4mQ9bT', 0), 'xK4mQ9bT0')
        self.assertEqual(make_short_id('xK4mQ9bT', 61), 'xK4mQ9bTZ')
        self.assertEqual(make_short_id('xK4mQ9bT', 62), 'xK4mQ9bT10')

    def test_prefix_preserved(self):
        """The short ID always starts with the prefix."""
        prefix = 'abcd1234'
        for i in [0, 1, 100, 10000]:
            sid = make_short_id(prefix, i)
            self.assertTrue(sid.startswith(prefix),
                            f"make_short_id({prefix!r}, {i})={sid!r} doesn't start with prefix")

    def test_sequential_ids_unique(self):
        prefix = 'testPFX0'
        ids = [make_short_id(prefix, i) for i in range(10000)]
        self.assertEqual(len(ids), len(set(ids)))

    def test_different_prefixes_different_ids(self):
        """Same index with different prefixes produces different short IDs."""
        id1 = make_short_id('prefix01', 42)
        id2 = make_short_id('prefix02', 42)
        self.assertNotEqual(id1, id2)

    def test_all_chars_valid(self):
        """Short IDs contain only base62 characters."""
        prefix = 'aB3dEf9H'
        for i in [0, 1, 61, 62, 3844, 10**6]:
            sid = make_short_id(prefix, i)
            self.assertTrue(all(c in BASE62_CHARS for c in sid),
                            f"Non-base62 char in {sid!r}")


class TestCrossValidation(unittest.TestCase):
    """Verify Python client encoding matches expected server-side values.

    The server has its own identical implementation with a base62_decode
    function. These tests pin specific encode values to catch drift.
    """

    KNOWN_PAIRS = [
        (0, '0'),
        (1, '1'),
        (10, 'a'),
        (35, 'z'),
        (36, 'A'),
        (61, 'Z'),
        (62, '10'),
        (3844, '100'),
        (238328, '1000'),
    ]

    def test_known_encodings(self):
        for num, expected in self.KNOWN_PAIRS:
            self.assertEqual(base62_encode(num), expected,
                             f"base62_encode({num}) expected {expected!r}")


if __name__ == '__main__':
    unittest.main()

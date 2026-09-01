"""\
Copyright (c) 2026, Flagstaff Solutions, LLC
All rights reserved.

Regression tests for publishing paper cuts surfaced by the compute demo
notebook: titles in non-center slots publishing as 'Anonymous Figure', and
spurious warnings for absent best-effort default packages.
"""
import unittest
import warnings

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from gofigr.backends.matplotlib import MatplotlibBackend
from gofigr.reproducible import (
    _build_clean_globals,
    get_default_packages,
    reset_default_packages,
    set_default_packages,
)


class TestGetTitleSlots(unittest.TestCase):
    def tearDown(self):
        plt.close('all')

    def _titled(self, **title_kwargs):
        fig, ax = plt.subplots()
        ax.plot([0, 1], [0, 1])
        if title_kwargs:
            ax.set_title(**title_kwargs)
        return fig

    def test_center_title(self):
        fig = self._titled(label='Centered')
        self.assertEqual(MatplotlibBackend().get_title(fig), 'Centered')

    def test_left_and_right_titles_are_found(self):
        fig = self._titled(label='Leftie', loc='left')
        self.assertEqual(MatplotlibBackend().get_title(fig), 'Leftie')
        fig = self._titled(label='Rightie', loc='right')
        self.assertEqual(MatplotlibBackend().get_title(fig), 'Rightie')

    def test_center_wins_over_left(self):
        fig = self._titled(label='Center')
        fig.axes[0].set_title('Left', loc='left')
        self.assertEqual(MatplotlibBackend().get_title(fig), 'Center')

    def test_suptitle_wins_and_untitled_is_none(self):
        fig = self._titled(label='Left only', loc='left')
        fig.suptitle('Super')
        self.assertEqual(MatplotlibBackend().get_title(fig), 'Super')
        self.assertIsNone(MatplotlibBackend().get_title(self._titled()))


class TestDefaultPackageWarnings(unittest.TestCase):
    def tearDown(self):
        reset_default_packages()

    def test_missing_default_package_is_silent(self):
        set_default_packages({'ghost': 'gofigr_test_no_such_module'})
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always')
            clean = _build_clean_globals(get_default_packages())
        self.assertEqual([w for w in caught if 'gofigr_test_no_such_module'
                          in str(w.message)], [])
        self.assertNotIn('ghost', clean)

    def test_missing_explicit_package_still_warns(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always')
            _build_clean_globals({'ghost': 'gofigr_test_no_such_module'})
        self.assertEqual(len(caught), 1)
        self.assertIn('gofigr_test_no_such_module', str(caught[0].message))


if __name__ == '__main__':
    unittest.main()

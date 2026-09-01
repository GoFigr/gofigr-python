"""\
Copyright (c) 2026, Flagstaff Solutions, LLC
All rights reserved.

Pickling a figure while matplotlib's savefig(bbox_inches='tight') state
lingers fails with "Can't get local object 'adjust_bbox.<locals>.<lambda>'"
— the publisher must strip those artifacts for the pickle and restore them.
"""
import inspect
import pickle
import types
import unittest

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import _tight_bbox
from matplotlib.transforms import Bbox

from gofigr.publisher import Publisher, _tight_bbox_artifacts_removed


def make_tight_bbox_stuck_figure():
    """A figure exactly in the state adjust_bbox leaves mid-render: local
    lambdas installed as axes locator and apply_aspect override."""
    fig, ax = plt.subplots()
    ax.plot([0, 1], [0, 1])
    ax.set_title('stuck')
    fig.canvas.draw()
    # adjust_bbox grew a `renderer` argument in newer matplotlib
    kwargs = {}
    if 'renderer' in inspect.signature(_tight_bbox.adjust_bbox).parameters:
        kwargs['renderer'] = fig.canvas.get_renderer()
    _tight_bbox.adjust_bbox(fig, Bbox.from_bounds(0, 0, 4, 3), **kwargs)
    # restore_bbox deliberately NOT called
    return fig, ax


class TestTightBboxPickle(unittest.TestCase):
    def test_stuck_figure_is_unpicklable_without_help(self):
        fig, _ = make_tight_bbox_stuck_figure()
        with self.assertRaises(Exception):
            pickle.dumps(fig)

    def test_context_manager_enables_pickle_and_restores_state(self):
        fig, ax = make_tight_bbox_stuck_figure()
        locator_before = ax.get_axes_locator()
        self.assertIsNotNone(locator_before)
        self.assertIn('apply_aspect', ax.__dict__)

        with _tight_bbox_artifacts_removed(fig):
            data = pickle.dumps(fig)
        self.assertTrue(data)

        # The in-flight tight-bbox state is put back exactly as found
        self.assertIs(ax.get_axes_locator(), locator_before)
        self.assertIn('apply_aspect', ax.__dict__)

    def test_clean_figure_untouched_by_context_manager(self):
        fig, ax = plt.subplots()
        ax.plot([0, 1], [1, 0])
        with _tight_bbox_artifacts_removed(fig):
            pickle.dumps(fig)
        self.assertIsNone(ax.get_axes_locator())
        self.assertNotIn('apply_aspect', ax.__dict__)

    def test_get_pickle_data_recovers(self):
        fig, _ = make_tight_bbox_stuck_figure()
        stub_self = types.SimpleNamespace(save_pickle=True)
        stub_gf = types.SimpleNamespace(
            FileData=lambda name, data: types.SimpleNamespace(name=name, data=data))

        result = Publisher._get_pickle_data(stub_self, stub_gf, fig, None)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].name, 'figure.pickle')
        self.assertTrue(pickle.loads(result[0].data))


if __name__ == '__main__':
    unittest.main()

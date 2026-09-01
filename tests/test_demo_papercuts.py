"""\
Copyright (c) 2026, Flagstaff Solutions, LLC
All rights reserved.

Regression tests for publishing paper cuts surfaced by the compute demo
notebook: titles in non-center slots publishing as 'Anonymous Figure', and
spurious warnings for absent best-effort default packages.
"""
import io
import types
import unittest
import warnings

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import PIL.Image

from gofigr.backends.matplotlib import MatplotlibBackend
from gofigr.reproducible import (
    _build_clean_globals,
    get_default_packages,
    reset_default_packages,
    set_default_packages,
)
from gofigr.watermarks import DefaultWatermark


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


class TestPublishDpiIsDeterministic(unittest.TestCase):
    """figure_to_bytes must not inherit transiently-scaled figure dpi (e.g.
    IPython's retina renderer doubles fig.dpi mid-print), which inflated
    published images to 2x their intended size."""

    def tearDown(self):
        plt.close('all')
        matplotlib.rcParams['savefig.dpi'] = 'figure'

    def _png_size(self, fig):
        png = MatplotlibBackend().figure_to_bytes(fig, 'png', {})
        return PIL.Image.open(io.BytesIO(png)).size

    def test_numeric_savefig_dpi_wins_over_transient_fig_dpi(self):
        matplotlib.rcParams['savefig.dpi'] = 200
        fig, _ = plt.subplots(figsize=(8, 6), dpi=125)
        fig.dpi = 250  # simulate mid-retina-render state
        self.assertEqual(self._png_size(fig), (1600, 1200))

    def test_figure_mode_uses_original_dpi_not_transient(self):
        matplotlib.rcParams['savefig.dpi'] = 'figure'
        fig, _ = plt.subplots(figsize=(8, 6), dpi=125)
        self.assertEqual(fig._original_dpi, 125)
        fig.dpi = 250  # simulate mid-retina-render state
        self.assertEqual(self._png_size(fig), (1000, 750))

    def test_explicit_dpi_param_still_wins(self):
        matplotlib.rcParams['savefig.dpi'] = 200
        fig, _ = plt.subplots(figsize=(8, 6), dpi=125)
        png = MatplotlibBackend().figure_to_bytes(fig, 'png', {'dpi': 100})
        self.assertEqual(PIL.Image.open(io.BytesIO(png)).size, (800, 600))


def _make_mid_render_fig():
    fig, ax = plt.subplots(figsize=(8, 6), dpi=125)
    ax.scatter([0, 1, 2], [2, 0, 1], s=40)
    ax.set_title('mid-render')
    return fig


def _simulate_mid_render(fig):
    """Put a figure in the state the inline renderer holds it in during
    savefig(bbox_inches='tight') at retina dpi."""
    import inspect as _inspect
    from matplotlib import _tight_bbox
    from matplotlib.transforms import Bbox
    fig.canvas.draw()
    kwargs = {}
    if 'renderer' in _inspect.signature(_tight_bbox.adjust_bbox).parameters:
        kwargs['renderer'] = fig.canvas.get_renderer()
    _tight_bbox.adjust_bbox(fig, Bbox.from_bounds(0, 0, 7, 5), **kwargs)
    fig.dpi = 250


class TestMidRenderDeferral(unittest.TestCase):
    """Auto-publish triggered from inside IPython's inline tight-bbox render
    must NOT export the live figure (its transforms are rewritten for the
    in-flight render — exports come out garbled or inflated). Instead it
    defers to post_run_cell, when matplotlib has restored the figure."""

    def tearDown(self):
        plt.close('all')

    def _hook(self, fig):
        """Run Publisher.auto_publish_hook against a stub extension/backend,
        recording what happens."""
        from gofigr.jupyter import JupyterPublisher
        calls = {'published': [], 'deferred': [], 'suppressed': 0}

        backend = types.SimpleNamespace(find_figures=lambda shell, data: [fig])
        pub = JupyterPublisher.__new__(JupyterPublisher)
        pub.backends = [backend]
        pub.publish = lambda fig=None, backend=None, suppress_display=None: \
            calls['published'].append(fig)
        extension = types.SimpleNamespace(
            shell=None,
            add_deferred_publish=lambda f, b: calls['deferred'].append((f, b)))

        def suppress():
            calls['suppressed'] += 1
        JupyterPublisher.auto_publish_hook(pub, extension, data={},
                                           suppress_display=suppress)
        return calls

    def test_mid_render_figure_is_deferred_not_published(self):
        fig = _make_mid_render_fig()
        _simulate_mid_render(fig)
        calls = self._hook(fig)
        self.assertEqual(calls['published'], [])
        self.assertEqual([f for f, _ in calls['deferred']], [fig])
        self.assertEqual(calls['suppressed'], 1)

    def test_clean_figure_publishes_immediately(self):
        fig = _make_mid_render_fig()
        calls = self._hook(fig)
        self.assertEqual(calls['published'], [fig])
        self.assertEqual(calls['deferred'], [])
        self.assertEqual(calls['suppressed'], 0)

    def test_process_deferred_publishes_drains_queue(self):
        from gofigr.jupyter import _GoFigrExtension
        published = []
        ext = _GoFigrExtension.__new__(_GoFigrExtension)
        ext.publisher = types.SimpleNamespace(
            publish=lambda fig=None, backend=None: published.append(fig))
        fig = _make_mid_render_fig()
        ext.deferred_publishes = [(fig, 'backend')]

        ext.process_deferred_publishes()
        self.assertEqual(published, [fig])
        self.assertEqual(ext.deferred_publishes, [])

    def test_deferred_publish_failure_does_not_raise(self):
        from gofigr.jupyter import _GoFigrExtension

        def boom(fig=None, backend=None):
            raise RuntimeError('api down')
        ext = _GoFigrExtension.__new__(_GoFigrExtension)
        ext.publisher = types.SimpleNamespace(publish=boom)
        ext.deferred_publishes = [(_make_mid_render_fig(), 'backend')]
        ext.process_deferred_publishes()  # must not raise
        self.assertEqual(ext.deferred_publishes, [])


class TestWatermarkScaling(unittest.TestCase):
    """The watermark strip must scale with image width — a fixed 14px font
    and tiny QR are unreadable on retina-resolution publishes."""

    REVISION = types.SimpleNamespace(api_id='12345678-aaaa-bbbb-cccc-000000000000',
                                     _short_id='AbCdEf9012')

    def _strip_height(self, width):
        img = PIL.Image.new('RGB', (width, 600), 'white')
        out = DefaultWatermark().apply(img, self.REVISION)
        return out.height - img.height

    def test_strip_scales_with_image_width(self):
        h_ref = self._strip_height(800)
        h_2x = self._strip_height(1600)
        h_big = self._strip_height(2400)
        self.assertGreater(h_2x, 1.6 * h_ref)
        self.assertGreater(h_big, h_2x)

    def test_scale_is_clamped(self):
        self.assertEqual(DefaultWatermark.image_scale(400), 1.0)
        self.assertEqual(DefaultWatermark.image_scale(800), 1.0)
        self.assertEqual(DefaultWatermark.image_scale(1600), 2.0)
        self.assertEqual(DefaultWatermark.image_scale(100000), 4.0)

    def test_pad_matches_applied_watermark_height(self):
        img = PIL.Image.new('RGB', (1600, 600), 'white')
        wm = DefaultWatermark()
        padded = wm.pad_for_watermark(img)
        applied = wm.apply(img, self.REVISION)
        self.assertEqual(padded.height, applied.height)

    def test_legacy_subclass_without_scale_still_works(self):
        class LegacyWatermark(DefaultWatermark):
            def get_watermark(self, revision):  # no scale param
                return super().get_watermark(revision)

        img = PIL.Image.new('RGB', (1600, 600), 'white')
        out = LegacyWatermark().apply(img, self.REVISION)
        self.assertGreater(out.height, img.height)


if __name__ == '__main__':
    unittest.main()

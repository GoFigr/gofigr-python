"""\
Copyright (c) 2025-2026, Flagstaff Solutions, LLC
All rights reserved.

Publisher for use inside a Pyodide Web Worker (browser-based Python). Uses
the server-side derive + append_data endpoints for efficient publication:

  1. derive  -- clones ExternalData from source, returns new revision api_id
  2. watermark -- uses api_id to generate QR watermark (client-side)
  3. append_data -- uploads watermarked images, code, manifest
"""
import io
import json
import logging
import platform
from http import HTTPStatus

import PIL

from gofigr.backends import get_backend, GoFigrBackend
from gofigr.backends.matplotlib import MatplotlibBackend
from gofigr.cleanroom import serialize_params
from gofigr.models import CodeLanguage
from gofigr.reproducible import _reproducible_context
from gofigr.watermarks import DefaultWatermark

try:
    from gofigr.backends.plotly import PlotlyBackend
except ImportError:
    PlotlyBackend = None

logger = logging.getLogger(__name__)

PYODIDE_BACKENDS = tuple(
    b for b in (MatplotlibBackend, PlotlyBackend) if b is not None
)


def _make_backend(backend):
    if isinstance(backend, GoFigrBackend):
        return backend
    return backend()


class _RevisionStub:
    """Minimal object exposing api_id, used by watermark.apply()."""
    def __init__(self, api_id):
        self.api_id = api_id


class PyodidePublisher:
    """Publishes figure revisions from a Pyodide Web Worker using the derive
    endpoint for efficient data reuse."""

    def __init__(self,
                 gf,
                 analysis,
                 source_revision_api_id,
                 watermark=None,
                 image_formats=("png", "svg"),
                 backends=None):
        """
        :param gf: authenticated GoFigr instance
        :param analysis: GoFigr Analysis object (fetched)
        :param source_revision_api_id: API ID of the source revision to derive from
        :param watermark: Watermark instance (default: DefaultWatermark)
        :param image_formats: image formats to save
        :param backends: figure backends to use
        """
        self.gf = gf
        self.analysis = analysis
        self.source_revision_api_id = source_revision_api_id
        self.watermark = watermark or DefaultWatermark()
        self.image_formats = image_formats
        self.backends = [_make_backend(b) for b in (backends or PYODIDE_BACKENDS)]
        self._last_watermarked_png = {}

    def _resolve_target(self, fig, target, backend):
        """Find or create a Figure entity by title within self.analysis."""
        if target is not None:
            return self.gf.find_figure(self.analysis, target)

        fig_name = backend.get_title(fig)
        if fig_name is None:
            fig_name = "Anonymous Figure"
        return self.analysis.get_figure(fig_name, create=True)

    def _get_image_data(self, fig, rev_stub, backend, image_options):
        """Extract image data in requested formats, apply watermark to PNG."""
        if image_options is None:
            image_options = {}

        image_data = []
        watermarked_png_bytes = None

        for fmt in self.image_formats:
            if fmt.lower() not in backend.get_supported_image_formats():
                continue

            try:
                raw_bytes = backend.figure_to_bytes(fig, fmt, image_options)
            except Exception as e:
                logger.warning("Could not obtain figure in %s format: %s", fmt, e)
                continue

            image_data.append(self.gf.ImageData(
                name="figure", format=fmt, data=raw_bytes, is_watermarked=False
            ))

            if fmt.lower() == "png":
                img = PIL.Image.open(io.BytesIO(raw_bytes))
                img.load()
                wm_img = self.watermark.apply(img, rev_stub)
                bio = io.BytesIO()
                wm_img.save(bio, format="png")
                watermarked_png_bytes = bio.getvalue()

                image_data.append(self.gf.ImageData(
                    name="figure", format="png", data=watermarked_png_bytes, is_watermarked=True
                ))

        return image_data, watermarked_png_bytes

    def _build_clean_room_data(self, ctx):
        """Build source code, manifest, and DataFrame param data objects."""
        data_list = []
        data_list.append(self.gf.CodeData(
            name="Clean Room Source",
            language=CodeLanguage.PYTHON,
            format="clean_room",
            contents=ctx.source_code,
            is_clean_room=True,
        ))

        bundle = serialize_params(ctx.parameters, param_descriptors=ctx.param_descriptors)

        manifest = {
            "language": "python",
            "language_version": platform.python_version(),
            "function_name": ctx.function_name,
            "packages": ctx.package_versions,
            "imports": ctx.imports,
            "parameters": bundle.manifest,
        }

        data_list.append(self.gf.TextData(
            name="Clean Room Manifest",
            format="json",
            contents=json.dumps(manifest, ensure_ascii=False),
            is_clean_room=True,
        ))

        for param_name, parquet_bytes in bundle.dataframes.items():
            data_list.append(self.gf.TableData(
                name=param_name,
                format="parquet",
                data=parquet_bytes,
                is_clean_room=True,
            ))

        return data_list

    def publish(self, fig=None, target=None, backend=None,
                image_options=None, metadata=None):
        """Publish a figure as a derived revision.

        Flow:
          1. Resolve target Figure entity by title
          2. POST derive endpoint -> new revision with cloned ExternalData, api_id
          3. Generate watermark using api_id
          4. POST append_data -> upload watermarked images, code, manifest

        :param fig: matplotlib/plotly figure
        :param target: target Figure entity (optional, resolved by title if None)
        :param backend: GoFigrBackend instance (optional, inferred from fig)
        :param image_options: backend-specific image options
        :param metadata: JSON metadata dict
        :return: dict with revision data + watermarked_png bytes attached
        """
        if fig is None and backend is None:
            raise ValueError("You must specify a figure to publish.")

        if fig is None:
            fig = backend.get_default_figure()

        if backend is None:
            backend = get_backend(fig, self.backends)

        target_figure = self._resolve_target(fig, target, backend)
        if target_figure is None:
            raise ValueError("Could not resolve target figure.")
        if getattr(target_figure, 'api_id', None) is None:
            target_figure.fetch()

        # Step 1: Create derived revision via derive endpoint (clones DataFrames)
        derive_payload = {'figure': target_figure.api_id}
        if metadata:
            derive_payload['metadata'] = metadata
        derive_resp = self.gf._post(
            f"revision/{self.source_revision_api_id}/derive/",
            json=derive_payload,
            expected_status=(HTTPStatus.OK, HTTPStatus.CREATED),
        )
        derived = derive_resp.json()
        derived_api_id = derived['api_id']

        # Step 2: Generate watermark using the derived revision's api_id
        rev_stub = _RevisionStub(derived_api_id)

        # Step 3: Extract images and apply watermark
        image_data, watermarked_png = self._get_image_data(fig, rev_stub, backend, image_options)

        # Step 4: Build additional data (code, manifest)
        all_data = list(image_data)
        ctx = _reproducible_context.get()
        if ctx is not None:
            all_data.extend(self._build_clean_room_data(ctx))

        # Step 5: Upload data via append_data endpoint
        serialized_data = [d.to_json() for d in all_data]
        self.gf._post(
            f"revision/{derived_api_id}/append_data/",
            json={'data': serialized_data},
        )

        self._last_watermarked_png[derived_api_id] = watermarked_png
        return derived

    def last_watermarked_image(self, result):
        """Return the last watermarked PNG bytes for a publish result."""
        api_id = result.get('api_id', '') if isinstance(result, dict) else ''
        return self._last_watermarked_png.get(api_id)

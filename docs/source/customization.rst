Customization
==============


QR code & watermarks
*********************

You can customize the QR code (or disable it altogether) by specifying
a custom watermark in the call to :func:`gofigr.jupyter.configure`. See :class:`gofigr.watermarks.DefaultWatermark` for other parameters.

.. code:: python

    %reload_ext gofigr

    from gofigr.jupyter import *
    configure(analysis=FindByName("Documentation examples", create=True),
              auto_publish=True,
              watermark=DefaultWatermark(show_qr_code=False))



Annotators
***********

GoFigr implements ``Annotators``, an extensible framework for *automatically* including relevant
data when publishing revisions. You can use this mechanism to automatically
attach the output of ``pip freeze``, for example.

Out of the box, GoFigr includes the following annotators:

* :class:`gofigr.jupyter.NotebookMetadataAnnotator`: name & path of the current notebook
* :class:`gofigr.jupyter.CellCodeAnnotator`: code of the Jupyter cell
* :class:`gofigr.jupyter.CellIdAnnotator`: Jupyter Cell ID (only available in Jupyter Lab)
* :class:`gofigr.jupyter.PipFreezeAnnotator`: output of `pip freeze`
* :class:`gofigr.jupyter.SystemAnnotator`: output of `uname -a`
* :class:`gofigr.jupyter.EnvironmentAnnotator`: Python version and kernel path
* :class:`gofigr.jupyter.BackendAnnotator`: Figure backend (e.g. matplotlib, plotly)
* :class:`gofigr.jupyter.HistoryAnnotator`: Jupyter execution history

Notebook name & path
--------------------------------
GoFigr uses `ipynbname` to infer the name & path of the currently running notebook. While this works well most of the
time, it may not work in certain configurations. For example, it doesn't work if the notebook is executed
programmatically with `nbconvert`. Other exceptions may exist, as well.

GoFigr will show a warning if the notebook name or path cannot be obtained. To fix, you can specify them in the call
to configure:

.. code:: python

    %reload_ext gofigr

    from gofigr.jupyter import *
    configure(analysis=FindByName("Documentation examples", create=True),
              auto_publish=True,
              notebook_name="my notebook",
              notebook_path="/path/to/notebook.ipynb")



Implementing custom annotators
--------------------------------

To implement a custom annotator, simply subclass :class:`gofigr.jupyter.Annotator`. For example, here's how `pip freeze`
is implemented:

.. code:: python

    class PipFreezeAnnotator(Annotator):
        """Annotates revisions with the output of pip freeze"""
        def annotate(self, revision):
            try:
                output = subprocess.check_output(["pip", "freeze"]).decode('ascii')
            except subprocess.CalledProcessError as e:
                output = e.output

            revision.data.append(_GF_EXTENSION.gf.TextData(name="pip freeze", contents=output))
            return revision

You can annotate revisions with:

* :class:`gofigr.models.ImageData`
* :class:`gofigr.models.CodeData`
* :class:`gofigr.models.TextData`
* :class:`gofigr.models.TableData`


Specifying annotators
******************************

You can override the default annotators in the call to :func:`gofigr.jupyter.configure`:

.. code:: python

    %reload_ext gofigr

    from gofigr.jupyter import *
    from gofigr.watermarks import DefaultWatermark

    configure(..., annotators=DEFAULT_ANNOTATORS)


Widgets
***********

When used with Jupyter, GoFigr will display a widget under each published figure.
The widget is customizable -- you can override it by passing ``widget_class`` to :func:`gofigr.jupyter.configure`.

For a full list of supported widget classes, see :mod:`gofigr.widget`.

Detailed (default)
----------------------

.. figure:: images/detailed_widget.png
  :alt: Detailed Jupyter Widget


Compact
----------------------

.. figure:: images/compact_widget.png
  :alt: Compact Jupyter Widget


Minimal
----------------------

.. figure:: images/minimal_widget.png
  :alt: Minimal Jupyter Widget


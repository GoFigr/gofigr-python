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

* :class:`gofigr.jupyter.NotebookNameAnnotator`: annotates revisions with the name & path of the current notebook
* :class:`gofigr.jupyter.CellCodeAnnotator`: annotates revisions with the code of the Jupyter cell
* :class:`gofigr.jupyter.CellIdAnnotator`: annotates revisions with the Jupyter Cell ID (only available in Jupyter Lab)
* :class:`gofigr.jupyter.PipFreezeAnnotator`: annotates revisions with the output of `pip freeze`
* :class:`gofigr.jupyter.SystemAnnotator`: annotates revisions with `uname -a`

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


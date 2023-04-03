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

* :class:`gofigr.jupyter.CellCodeAnnotator`: annotates revisions with the code of the Jupyter cell
* :class:`gofigr.jupyter.PipFreezeAnnotator`: annotates revisions with the output of `pip freeze`
* :class:`gofigr.jupyter.SystemAnnotator`: annotates revisions with `uname -a`

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


Specifying default annotators
******************************

You can override the default annotators in the call to :func:`gofigr.jupyter.configure`:

.. code:: python

    %reload_ext gofigr

    from gofigr.jupyter import *
    from gofigr.watermarks import DefaultWatermark

    configure(..., annotators=DEFAULT_ANNOTATORS)


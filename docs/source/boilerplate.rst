Jupyter Configuration
====================================

Simple
************

.. code:: python

    %load_ext gofigr

    from gofigr.jupyter import *

    configure(analysis=FindByName("My Analysis", create=True))

Complex
***************

The code below shows all the configurable options. You can pick and choose based
on your specific needs.

.. code:: python

    %reload_ext gofigr

    from gofigr.jupyter import *
    from gofigr.watermarks import DefaultWatermark

    configure(auto_publish=True,
              workspace=FindByName("Boilerplate Co", create=False),
              analysis=FindByName("Clinical Trial #1", create=True),
              default_metadata={'requested_by': "Alyssa",
                                'study': 'Pivotal Trial 1'},
              watermark=DefaultWatermark(show_qr_code=False),
              backends=(MatplotlibBackend, PlotlyBackend, Py3DmolBackend),
              annotators=DEFAULT_ANNOTATORS,
              widget_class=DetailedWidget,
              save_pickle=True)

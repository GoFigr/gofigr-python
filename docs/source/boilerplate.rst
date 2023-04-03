Jupyter Configuration Boilerplate
====================================

Place the following code at the top of your notebook. Note that only the
``analysis`` is required, but you can customize as needed:

.. code:: python

    %reload_ext gofigr

    from gofigr.jupyter import *
    from gofigr.watermarks import DefaultWatermark

    configure(auto_publish=True,
              workspace=FindByName("Boilerplate Co", create=False),
              analysis=FindByName("Clinical Trial #1", create=True),
              default_metadata={'requested_by': "Alyssa",
                                'study': 'Pivotal Trial 1'},
              watermark=DefaultWatermark(show_qr_code=False)
              annotators=DEFAULT_ANNOTATORS)

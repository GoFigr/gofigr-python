Compatibility
================

GoFigr requires Python 3.7 or later, and works with both the Jupyter Notebook (including upcoming Jupyter 7) and Jupyter Lab.

The GoFigr Jupyter extension has been tested with:

* ``python >= 3.7.16``
* ``notebook >= 6.5.4``
* ``jupyterlab >= 3.6.3``
* ``matplotlib >= 3.5.3``
* ``ipython >= 7.34.0``
* ``plotly >= 4.14.3``
* ``plotnine >= 0.12.4``

Library support
********************

GoFigr supports:

* matplotlib (including derivatives like seaborn)
* plotly
* plotnine
* py3dmol (experimental)

The plotly & py3dmol backends can export both static images as well as interactive plots.

All backends are enabled by default if their corresponding plotting libraries are installed.

We welcome patches which add support for new libraries at https://github.com/GoFigr/gofigr-python.


Customizing backends
**************************

You can enable/disable backends by passing a list to :func:`gofigr.jupyter.configure`. By default, all available
backends are enabled.

If manually specifying the plotnine backend, make sure it precedes the Matplotlib backend. Otherwise its figures may
be published as ordinary matplotlib figures.

.. code:: python

    %reload_ext gofigr

    from gofigr.jupyter import *
    from gofigr.backends.matplotlib import MatplotlibBackend
    from gofigr.backends.plotly import PlotlyBackend
    from gofigr.backends.plotnine import PlotnineBackend

    configure(analysis=FindByName("Documentation examples", create=True),
              auto_publish=True,
              watermark=DefaultWatermark(show_qr_code=False),
              backends=[PlotlyBackend, PlotnineBackend, MatplotlibBackend])

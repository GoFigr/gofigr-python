.. figure:: docs/source/images/logo_wide_light.png
  :alt: GoFigr.io logo

GoFigr - Lite
====================================
GoFigr (https://www.gofigr.io) is a service which provides sophisticated version control for figures.

If you cannot use the full GoFigr online service, we include a fully offline Jupyter plugin called `GoFigr Lite`.

GoFigr Lite embeds useful information in the figure itself, including:

* The author
* Notebook name
* Date

If the notebook is part of a git repo, we also include:

* Git commit hash
* QR code link to the commit on GitHub or BitBucket

The Lite plugin is licensed as open source software (MIT license) and is fully offline. No data
is saved or exchanged with GoFigr servers.


Jupyter compatibility
*************
We support modern Jupyter Lab, including the new Notebook 7+ interface.

If you see cryptic errors about ipywidgets or asyncio, we recommend upgrading to
latest versions:

.. code:: bash

    pip install --upgrade jupyterlab ipywidgets asyncio nest-asyncio


Unfortunately, we do not support the classic Jupyter Notebook (versions 6 or earlier).

Library support
***************
We support the most popular Python plotting libraries:

* matplotlib
* seaborn
* plotnine
* plotly


Example `lite` figure
*****************
.. figure:: docs/source/images/lite_example.png
  :alt: GoFigr Lite - example


Client setup
*************

First, install the ``gofigr`` client library (gofigr>=1.3.0 -- earlier versions don't support `lite`):

.. code:: bash

    $ pip install gofigr

This will install both a client library and a Jupyter extension. Verify
the extension installed correctly by clicking on the "extensions" tab in the top
left corner of Jupyter Lab. You may need to refresh the page and/or restart your
Jupyter instance:

.. figure:: docs/source/images/lite_extension.png
  :alt: GoFigr Lite extension


Usage
*****

To enable GoFigr lite in Jupyter, simply call `%load_ext gofigr.lite`
at the beginning of your Notebook. That's it! All your figures will
now automatically include details underneath.

.. figure:: docs/source/images/lite_in_jupyter_example.png
  :alt: GoFigr Lite extension - In Jupyter

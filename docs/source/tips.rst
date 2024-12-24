Tips & tricks
==============

Loading a published figure from stored pickle data
*****************************************************

If your figure was published with GoFigr > 0.17.0, GoFigr automatically stores a pickled
representation that you can load and modify later. Simply
call :func:`gofigr.jupyter.load_pickled_figure` with the API ID of the
figure revision you would like to unpickle. This will return
a backend-specific object, e.g. plt.Figure for matplotlib, which you
can then modify as needed.

.. code:: python

    fig = load_pickled_figure("b0fc47f0-9baf-46db-b7e7-dce2467d30f1")
    fig.gca().set_title("My updated title")
    fig.gca().set_xlabel("Timestamp")

    # Publish a new revision with an updated title
    publish(fig)


Attaching files to a figure
*****************************************************

GoFigr supports the attaching of files to each individual revision. To attach, call
:func:`gofigr.jupyter.publish` and pass a list of file locations. The files will
then appear under a separate "Files" tab in the GoFigr portal.

.. code:: python

    publish(fig=plt.gcf(), files=["power_analysis.xlsx", "protein-coding_gene.txt"])


Downloading files
*****************************************************

You can use :func:`gofigr.jupyter.download_file` or :func:`gofigr.jupyter.download_all`
to download files attached to a revision:

.. code:: python

    # Download single file
    download_file("851a3f22-126e-474c-89ca-65e6acf4a0cb",  # Revision ID
                  "my_file.xlsx",  # file name
                  ".")  # destination directory

    # Download all
    download_all("851a3f22-126e-474c-89ca-65e6acf4a0cb",  # Revision ID
                 ".")  # destination directory

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

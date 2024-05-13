import os

import gofigr as gf
from datetime import *
from gofigr.backends.matplotlib import MatplotlibBackend

import matplotlib.pyplot as plt
import seaborn as sns
import pandas as pd

# Create a GoFigr client and grab the default workspace
client = gf.GoFigr(api_key=os.environ['API_KEY'])
workspace, = client.workspaces

# GoFigr can save any image even if we don't have an official backend, but we use the MPL backend
# here for some convenience functions (like converting a figure to a bytes array).
mplb = MatplotlibBackend()

# Each workspace will contain multiple analyses. Here we find pipeline results or
# create it if it doesn't exist.
ana = workspace.get_analysis("Pipeline results", create=True).fetch()

# The specific figure we want to track revisions for.
target_fig = ana.get_figure(name="Replicate comparison", create=True)

# Plot our replicate data
df = pd.DataFrame({'x': range(10), 'y': range(10)})

plt.figure()
sns.scatterplot(data=df, x='x', y='y')
plt.title(f"Replicate plot: {datetime.now()}")

# Create a new revision and save it. GoFigr will persist the image and the attached data frame.
rev = client.Revision(figure=target_fig,
                      metadata={"Study ID": 12345,
                                "Initiated by": "Mark"}).create()
rev.image_data = [client.ImageData(name="figure", format="png", is_watermarked=False,
                                   data=mplb.figure_to_bytes(plt.gcf(), "png", {}))]
rev.table_data = [client.TableData(name="source data", dataframe=df)]
rev.save()

print(f"Published to {rev.revision_url}")

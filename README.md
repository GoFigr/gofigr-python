# GoFigr Python Client Tutorial

This tutorial will guide you through installing, configuring, and using the GoFigr Python client library for version control of figures and data assets.

## Table of Contents

1. [Installation](#installation)
2. [Initial Configuration](#initial-configuration)
3. [Using GoFigr in Jupyter](#using-gofigr-in-jupyter)
   - [Auto-Configured Setup](#auto-configured-setup)
   - [Custom Configuration](#custom-configuration)
4. [Using GoFigr in Scripts](#using-gofigr-in-scripts)
5. [Asset Tracking and Data Reading](#asset-tracking-and-data-reading)

---

## Installation

### Prerequisites

Before you begin, create a free account at [https://app.gofigr.io/register](https://app.gofigr.io/register).

### Install the GoFigr Client

Install the GoFigr Python client library using pip:

```bash
pip install gofigr
```

This installs both the client library and the IPython extension (compatible with Jupyter, VSCode, and others).

---

## Initial Configuration

After installation, configure GoFigr with your credentials and default workspace using the `gfconfig` command-line tool.

### Basic Configuration

Run `gfconfig` and follow the prompts:

```bash
gfconfig
```

You'll be prompted for:
- **Username**: Your GoFigr username
- **Password**: Your GoFigr password
- **API Key** (optional): Leave blank to generate a new key, or provide an existing one
- **Key Name**: A descriptive name for your API key (e.g., "My Laptop", "Server-01")
- **Default Workspace**: Select from your available workspaces

Example session:

```
$ gfconfig
------------------------------
GoFigr configuration
------------------------------
Username: alyssa
Password:
Verifying connection...
  => Authenticated successfully
API key (leave blank to generate a new key):
Key name: Alyssa's Macbook
  => Your new API key will be saved to /Users/alyssa/.gofigr
  => Connected successfully

Please select a default workspace:
  [ 1] - Scratchpad - alyssa's personal workspace  - API ID: c6ecd353-321d-4089-b5aa-d94bf0ecb09a
Selection [1]: 1

Configuration saved to /Users/alyssa/.gofigr. Happy analysis!
```

### Advanced Configuration

For more control, run `gfconfig --advanced`:

```bash
gfconfig --advanced
```

This allows you to customize:
- **API URL**: Default is `https://api.gofigr.io` (usually fine to accept default)
- **Auto-publish**: Whether to automatically capture figures in Jupyter (default: Yes)
- **Default revision metadata**: JSON metadata to store with each figure revision

Example:

```
$ gfconfig --advanced
------------------------------
GoFigr configuration
------------------------------
Username: mpacula
Password:
API URL [https://api.gofigr.io]:
Verifying connection...
  => Connected successfully
Auto-publish all figures [Y/n]: y
Default revision metadata (JSON): {"study": "First in Human trial"}

Please select a default workspace:
  [ 1] - Primary Workspace  - API ID: c6ecd353-321d-4089-b5aa-d94bf0ecb09a
Selection [1]: 1

Configuration saved to /Users/maciej/.gofigr. Happy analysis!
```

### Environment Variables (Optional)

Instead of using a configuration file, you can set environment variables:

- `GF_USERNAME`: Your GoFigr username
- `GF_PASSWORD`: Your GoFigr password
- `GF_API_KEY`: Your API key (alternative to username/password)
- `GF_WORKSPACE`: Workspace API ID
- `GF_ANALYSIS`: Analysis API ID
- `GF_URL`: API URL (default: `https://api.gofigr.io`)
- `GF_AUTO_PUBLISH`: `true` or `false`

---

## Using GoFigr in Jupyter

GoFigr works seamlessly with both Jupyter Notebook and Jupyter Lab. There are two ways to set it up: auto-configured (simplest) and custom configuration.

### Auto-Configured Setup

The simplest way to use GoFigr in Jupyter is with auto-configuration. Just load the extension:

```python
%load_ext gofigr
```

That's it! GoFigr will:
- Automatically use your default workspace from `gfconfig`
- Create or use an analysis named after your notebook
- Enable auto-publish (automatically captures all figures)
- Use default settings from your configuration

All figures you create will be automatically published to GoFigr. For example:

```python
%load_ext gofigr

import matplotlib.pyplot as plt
import pandas as pd
import numpy as np

# Create a simple plot
df = pd.DataFrame({'x': np.random.randn(100), 'y': np.random.randn(100)})
plt.scatter(df['x'], df['y'])
plt.title('Random Scatter Plot')

# This figure is automatically published!
```

The figure will appear with a QR code and unique revision ID, allowing you to track it in the GoFigr web app.

### Custom Configuration

If you need more control, use the `configure()` function after loading the extension:

```python
%load_ext gofigr

from gofigr.jupyter import configure, FindByName, ApiId, NotebookName

# Custom configuration
configure(
    workspace=FindByName("Primary Workspace", create=False),
    analysis=FindByName("My Analysis", create=True),
    auto_publish=True,
    default_metadata={
        'requested_by': "Alyssa",
        'study': 'Pivotal Trial 1'
    }
)
```

#### Configuration Options

- **`workspace`**: Specify the workspace to use
  - `FindByName("Workspace Name", create=False)`: Find by name (default: don't create)
  - `ApiId("uuid-string")`: Use specific workspace API ID
  - `None`: Use default from `gfconfig`

- **`analysis`**: Specify the analysis to use
  - `FindByName("Analysis Name", create=True)`: Find or create by name
  - `NotebookName()`: Use notebook name as analysis name (default)
  - `ApiId("uuid-string")`: Use specific analysis API ID

- **`auto_publish`**: If `True`, all figures are automatically published (default: `True`)

- **`default_metadata`**: Dictionary of metadata to store with each revision

- **`api_key`**: Override API key (if not using default from `gfconfig`)

#### Specifying Names vs. IDs

You can mix and match name-based and ID-based lookups:

```python
from gofigr.jupyter import configure, FindByName, ApiId

configure(
    workspace=ApiId("59da9bdb-2095-47a9-b414-c029f8a00e0e"),  # Use API ID
    analysis=FindByName("My Analysis", create=True)           # Use name lookup
)
```

#### Manual Publishing

If you set `auto_publish=False`, you can manually publish figures using the `publish()` function:

```python
%load_ext gofigr

from gofigr.jupyter import configure, FindByName

configure(auto_publish=False, analysis=FindByName("My Analysis", create=True))

import matplotlib.pyplot as plt

# Create a figure
plt.plot([1, 2, 3, 4], [1, 4, 9, 16])
plt.title('Manual Publish Example')

# Manually publish it
from gofigr.jupyter import publish
publish(fig=plt.gcf(), target=FindByName("My Figure", create=True))
```

---

## Using GoFigr in Scripts

You can use GoFigr in standalone Python scripts (outside Jupyter) using the `Publisher` class from `gofigr.publisher`.

### Basic Script Example

```python
import matplotlib.pyplot as plt
import pandas as pd
from gofigr.publisher import Publisher

# Initialize the publisher with workspace and analysis names
pub = Publisher(workspace="My Workspace", analysis="Script Analysis")

# Create a figure
df = pd.DataFrame({'x': range(10), 'y': [i**2 for i in range(10)]})
plt.plot(df['x'], df['y'])
plt.title('Quadratic Function')

# Publish the figure
pub.publish(plt.gcf())

print("Figure published!")
```

### Using API Keys in Scripts

If you've run `gfconfig`, the publisher will automatically use your saved API key. Alternatively, you can specify it explicitly:

```python
from gofigr.publisher import Publisher

pub = Publisher(
    workspace="My Workspace",
    analysis="Script Analysis",
    api_key="your-api-key-here"  # pragma: allowlist secret
)
```

### Complete Script Example

```python
import seaborn as sns
import matplotlib.pyplot as plt
import plotly.express as px
from gofigr.publisher import Publisher

# Setup GoFigr Publisher
pub = Publisher(workspace="Testz", analysis="Penguin Analysis")

# Load data
penguins = sns.load_dataset("penguins")

# Create and publish a Seaborn plot
print("Generating and publishing Seaborn scatter plot...")
sns.scatterplot(
    data=penguins,
    x="flipper_length_mm",
    y="bill_length_mm",
    hue="species"
)
plt.title("Penguin Bill Length vs. Flipper Length (Seaborn)")
pub.publish(plt.gcf())

# Create and publish a Plotly plot
print("Generating and publishing Plotly scatter plot...")
fig = px.scatter(
    penguins,
    x="flipper_length_mm",
    y="bill_length_mm",
    color="species",
    title="Penguin Bill Length vs. Flipper Length (Plotly)"
)
pub.publish(fig)
```

---

## Asset Tracking and Data Reading

GoFigr provides powerful asset tracking capabilities that automatically version and track data files used in your analyses. This ensures reproducibility by linking your figures to the exact data versions used to create them.

### Understanding Asset Sync

The `AssetSync` class provides drop-in replacements for file reading operations that:
1. Calculate checksums for your data files
2. Upload new or changed files to GoFigr
3. Track which data versions were used in your analysis
4. Link figures to the data assets they used

### Using Data Reading Methods

After initializing a GoFigr client, you can use data reading methods like `gf.read_csv()`, `gf.read_excel()`, etc., instead of pandas methods. These automatically sync and track your data assets.

#### In Jupyter

When you use `%load_ext gofigr`, a `gf` object is automatically available in your namespace:

```python
%load_ext gofigr

import pandas as pd

# Use gf.read_csv instead of pd.read_csv
df = gf.read_csv('data/penguins.csv')

# The DataFrame now has metadata linking it to the tracked asset
print(df.attrs.get('_gofigr_revision'))  # Shows the asset revision ID
```

#### In Scripts

In standalone scripts, initialize a GoFigr client first:

```python
from gofigr import GoFigr

# Initialize client
gf = GoFigr()  # Uses credentials from gfconfig or environment variables

# Use data reading methods - they work just like pandas methods
df = gf.read_csv('data/penguins.csv')
excel_data = gf.read_excel('data/experiment.xlsx')
json_data = gf.read_json('data/config.json')
```

### Supported Reading Methods

GoFigr provides drop-in replacements for these pandas reading functions:

- `gf.read_csv()` - CSV files
- `gf.read_excel()` - Excel files
- `gf.read_json()` - JSON files
- `gf.read_html()` - HTML tables
- `gf.read_parquet()` - Parquet files
- `gf.read_feather()` - Feather files
- `gf.read_hdf()` - HDF5 files
- `gf.read_pickle()` - Pickle files
- `gf.read_sas()` - SAS files

All methods accept the same parameters as their pandas counterparts.

### Manual Asset Syncing

You can also manually sync assets without reading them:

```python
# In Jupyter (gf is already available)
gf.sync.sync('data/penguins.csv')

# In scripts
from gofigr import GoFigr
gf = GoFigr()
gf.sync.sync('data/penguins.csv')
```

The `sync()` method:
- Calculates the file's checksum
- Uploads the file if it's new or changed
- Returns the existing revision if the file hasn't changed
- Displays a widget (in Jupyter) showing the asset details

### Tracking Assets with File Handles

You can use `gf.sync.open()` as a drop-in replacement for Python's `open()`:

```python
# In Jupyter
with gf.sync.open('data/raw_data.txt', 'r') as f:
    content = f.read()

# In scripts
from gofigr import GoFigr
gf = GoFigr()
with gf.sync.open('data/raw_data.txt', 'r') as f:
    content = f.read()
```

This automatically syncs the file before opening it.

### Viewing Tracked Assets

To see all assets you've tracked in the current session:

```python
# In Jupyter
print(gf.sync.revisions)  # List of all tracked asset revisions

# Access specific revision
for revision in gf.sync.revisions:
    print(f"Asset: {revision.asset.name}, Revision: {revision.api_id}")
```

### Linking Figures to Data Assets

When you publish a figure, GoFigr automatically tracks which data assets were used. The DataFrame objects created with `gf.read_*()` methods have an `attrs` dictionary containing the asset revision ID:

```python
# Load data
df = gf.read_csv('data/penguins.csv')

# Create and publish a figure
import matplotlib.pyplot as plt
plt.scatter(df['x'], df['y'])
pub.publish(plt.gcf())

# The figure is automatically linked to the data asset revision
# You can see this connection in the GoFigr web app
```

### Complete Asset Tracking Example

Here's a complete example showing asset tracking in action:

```python
%load_ext gofigr

from gofigr.jupyter import configure, FindByName
import matplotlib.pyplot as plt
import pandas as pd

# Configure GoFigr
configure(
    workspace=FindByName("My Workspace"),
    analysis=FindByName("Data Analysis", create=True)
)

# Load data using GoFigr's tracked reading methods
df = gf.read_csv('data/experiment_results.csv')
metadata = gf.read_json('data/experiment_config.json')

# Access the tracked asset revision IDs
data_revision_id = df.attrs.get('_gofigr_revision')
config_revision_id = metadata.attrs.get('_gofigr_revision')

print(f"Data asset revision: {data_revision_id}")
print(f"Config asset revision: {config_revision_id}")

# Create a figure using the tracked data
plt.figure(figsize=(10, 6))
plt.plot(df['time'], df['value'])
plt.title(f"Experiment Results (Config: {metadata.get('experiment_id')})")
plt.xlabel('Time')
plt.ylabel('Value')

# The figure will be automatically published and linked to the data assets
# All of this is tracked in GoFigr for full reproducibility!
```

### Benefits of Asset Tracking

1. **Reproducibility**: Know exactly which data version was used for each figure
2. **Change Detection**: Automatically detect when data files change
3. **Deduplication**: Same file content = same revision (saves storage)
4. **Collaboration**: Share exact data versions with your team
5. **Audit Trail**: Complete history of which data was used when

---

## Next Steps

- Explore the [GoFigr Web App](https://app.gofigr.io) to view your published figures and tracked assets
- Check out the [API Documentation](https://gofigr.io/docs) for advanced features
- Learn about [sharing and collaboration features](https://gofigr.io/docs/sharing) in GoFigr

---

## Troubleshooting

### Authentication Errors

If you get authentication errors:
1. Run `gfconfig` again to update your credentials
2. Check that your API key is valid in the GoFigr web app
3. Verify environment variables if using them

### Asset Sync Issues

If asset syncing fails:
1. Check file permissions
2. Verify the file exists at the specified path
3. Check your workspace permissions in the GoFigr web app
4. Review the logs for detailed error messages

For more help, visit [https://gofigr.io/support](https://gofigr.io/support).

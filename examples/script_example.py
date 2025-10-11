import seaborn as sns
import matplotlib.pyplot as plt
import plotly.express as px
from gofigr.publisher import Publisher

# --- Setup GoFigr Publisher ---
# Initialize the publisher, specifying your workspace and analysis name.
pub = Publisher(workspace="Testz", analysis="Penguin Analysis")

# --- Load Data ---
# Load the built-in penguins dataset
penguins = sns.load_dataset("penguins")

# ===============================================
# --- 1. Scatter Plot (Seaborn) ---
# ===============================================
print("Generating and publishing Seaborn scatter plot 1...")
sns.scatterplot(data=penguins, x="flipper_length_mm", y="bill_length_mm", hue="species")
plt.title("Penguin Bill Length vs. Flipper Length (Seaborn)")
pub.publish(plt.gcf()) # Publish the current figure

# ===============================================
# --- 2. Scatter Plot (Plotly) ---
# ===============================================
print("Generating and publishing Plotly scatter plot 1...")
fig1_px = px.scatter(
    penguins,
    x="flipper_length_mm",
    y="bill_length_mm",
    color="species",
    title="Penguin Bill Length vs. Flipper Length (Plotly)" # Plotly sets the title in the function
)
pub.publish(fig1_px) # Publish the Plotly figure

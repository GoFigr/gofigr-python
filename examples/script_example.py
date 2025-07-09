import seaborn as sns
import matplotlib.pyplot as plt
from gofigr.publisher import Publisher

print(__file__)

# --- Setup GoFigr Publisher ---
# Initialize the publisher, specifying your workspace and analysis name.
# clear=True will remove previous figures in the analysis on each run.
pub = Publisher(workspace="Testz", analysis="Penguin Analysis", clear=True)

# --- Load Data ---
# Load the built-in penguins dataset
penguins = sns.load_dataset("penguins")

# --- 1. Scatter Plot ---
print("Generating and publishing scatter plot...")
sns.scatterplot(data=penguins, x="flipper_length_mm", y="bill_length_mm", hue="species")
plt.title("Penguin Bill Length vs. Flipper Length")
pub.publish(plt.gcf()) # Publish the current figure
plt.show()
plt.close() # Close the figure to start fresh for the next one

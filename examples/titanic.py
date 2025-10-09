import seaborn as sns
import matplotlib.pyplot as plt
from gofigr.publisher import Publisher

# --- Setup GoFigr Publisher ---
# Initialize the publisher, specifying your workspace and analysis name.
# You can change "MyTitanicWorkspace" and "Titanic Analysis" as needed.
pub = Publisher(workspace="MyTitanicWorkspace", analysis="Titanic Analysis")

# --- Load Data ---
# Load the built-in titanic dataset
titanic = sns.load_dataset("titanic")

# ===============================================
# --- 1. Histogram (Distribution of Age) ---
# ===============================================
print("Generating and publishing Seaborn histogram (Age)...")
# Using histplot to visualize the distribution of 'age', colored by 'sex'
plt.figure(figsize=(10, 6)) # Create a new figure for this plot
sns.histplot(data=titanic, x="age", hue="sex", multiple="stack", kde=True)
plt.title("Distribution of Passenger Age by Sex (Seaborn)")
pub.publish(plt.gcf()) # Publish the current figure (gcf = Get Current Figure)
plt.close() # Close the figure to free up memory

# ===============================================
# --- 2. Scatter Plot (Age vs. Fare) ---
# ===============================================
print("Generating and publishing Seaborn scatter plot (Age vs. Fare)...")
# Using scatterplot to show the relationship between 'age' and 'fare', colored by 'survived' status
plt.figure(figsize=(10, 6)) # Create a new figure for this plot
sns.scatterplot(data=titanic, x="age", y="fare", hue="survived", style="pclass")
plt.title("Age vs. Fare Colored by Survival Status (Seaborn)")
pub.publish(plt.gcf()) # Publish the current figure
plt.close() # Close the figure

# ===============================================
# --- 3. Box Plot (Fare by Class) ---
# ===============================================
print("Generating and publishing Seaborn box plot (Fare by Class)...")
# Using boxplot to compare the distribution of 'fare' across 'pclass'
plt.figure(figsize=(10, 6)) # Create a new figure for this plot
sns.boxplot(data=titanic, x="pclass", y="fare", hue="sex")
plt.title("Fare Distribution by Passenger Class and Sex (Seaborn)")
pub.publish(plt.gcf()) # Publish the current figure
plt.close() # Close the figure

print("All Titanic plots generated and published to GoFigr.")

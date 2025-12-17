"""
GoFigr t-SNE Example - Demonstrating AI Diff Functionality

This example demonstrates how to use GoFigr with t-SNE visualization on a
high-dimensional omics-like dataset. By creating multiple revisions with different
parameters, you can use GoFigr's AI diff feature to automatically compare and
explain the differences between visualizations.

Dataset: Synthetic high-dimensional dataset (100 samples x 100 features)
mimicking gene expression data from omics experiments.
"""

import numpy as np
import matplotlib.pyplot as plt
from sklearn.manifold import TSNE
from sklearn.datasets import make_classification
from sklearn.preprocessing import StandardScaler
from gofigr.publisher import Publisher

# --- Setup GoFigr Publisher ---
# Initialize the publisher, specifying your workspace and analysis name.
pub = Publisher(workspace="Demo", analysis="t-SNE Analysis")

# --- Generate Synthetic Omics Dataset ---
# Create a high-dimensional dataset mimicking gene expression data
# 100 samples with 100 features (genes), 3 classes (cell types/conditions)
print("Generating synthetic omics dataset (100 samples x 100 features)...")
X, y = make_classification(
    n_samples=100,
    n_features=100,
    n_informative=50,  # 50 informative features
    n_redundant=10,    # 10 redundant features
    n_clusters_per_class=1,
    n_classes=3,
    random_state=42
)

# Standardize the data
scaler = StandardScaler()
X_scaled = scaler.fit_transform(X)

class_names = ['Class A', 'Class B', 'Class C']
colors = ['#E74C3C', '#3498DB', '#2ECC71']  # Red, Blue, Green

print(f"Dataset shape: {X_scaled.shape}")
print(f"Number of classes: {len(np.unique(y))}")

# --- Default t-SNE Visualization ---
# Run t-SNE with default perplexity (typically 30 for datasets of this size)
default_perplexity = 10
print(f"\nRunning t-SNE with perplexity={default_perplexity}...")

tsne_default = TSNE(n_components=2, perplexity=default_perplexity, random_state=42, max_iter=1000)
X_tsne_default = tsne_default.fit_transform(X_scaled)

# Create visualization
plt.figure(figsize=(10, 8))
for i, class_name in enumerate(class_names):
    mask = y == i
    plt.scatter(
        X_tsne_default[mask, 0],
        X_tsne_default[mask, 1],
        c=colors[i],
        label=class_name,
        alpha=0.7,
        s=120,
        edgecolors='black',
        linewidth=0.5
    )

plt.title(f't-SNE Visualization)', fontsize=14, fontweight='bold')
plt.xlabel('t-SNE Component 1', fontsize=12)
plt.ylabel('t-SNE Component 2', fontsize=12)
plt.legend(title='Class', fontsize=10, title_fontsize=11)
plt.grid(True, alpha=0.3)
plt.tight_layout()

# Publish the first revision
rev1 = pub.publish(
    fig=plt.gcf(),
    target="t-SNE Omics Dataset",
    metadata={
        'perplexity': default_perplexity,
        'n_samples': X_scaled.shape[0],
        'n_features': X_scaled.shape[1],
        'method': 't-SNE',
        'random_state': 42
    }
)
plt.close()

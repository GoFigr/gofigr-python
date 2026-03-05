#!/bin/env bash
# Setup pre-commit hooks for secret detection

set -e

echo "Setting up pre-commit hooks for secret detection..."

# Install pre-commit if not already installed
if ! command -v pre-commit &> /dev/null; then
    echo "Installing pre-commit..."
    pip install pre-commit
fi

# Install pre-commit hooks
echo "Installing pre-commit hooks..."
pre-commit install

# Generate initial secrets baseline if it doesn't exist
if [ ! -f .secrets.baseline ]; then
    echo "Generating initial secrets baseline..."
    pre-commit run --all-files detect-secrets > /dev/null 2>&1 || true
    echo "⚠️  Please review .secrets.baseline and commit it to the repository"
else
    echo "✅ Secrets baseline already exists"
fi

echo ""
echo "✅ Pre-commit hooks installed successfully!"
echo ""
echo "The hooks will now run automatically on every commit."
echo "To run manually: pre-commit run --all-files"
echo "To skip hooks (not recommended): git commit --no-verify"

#!/bin/env bash
set -e

source venv/bin/activate
pip install build hatch twine
hatch build

#!/bin/env bash
set -e

source venv/bin/activate
pylint --output-format=colorized gofigr/ --ignore-paths=gofigr/_version.py

#!/bin/env bash
set -e

pylint --output-format=colorized gofigr/ --ignore-paths=gofigr/_version.py

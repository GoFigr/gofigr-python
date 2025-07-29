#!/bin/env bash
source venv/bin/activate
cd docs/
rm -rf build
mkdir -p build
make html

tar -zcvf gofigr-docs-$( cat ../version.txt ).tar.gz -C build/html .

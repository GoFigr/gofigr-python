#!/usr/bin/env bash
set -e

GF_DIR=$( readlink -f $( dirname "$0" )/../../ )

WORKING_DIR=$1
PYTHON_VERSION=$2
SERVICE=$3
DEPENDENCIES=$4

mkdir -p "$WORKING_DIR"
cd "$WORKING_DIR"

rm -rf venv/
virtualenv -p "$PYTHON_VERSION" venv/
source venv/bin/activate
pip install --upgrade pip

cd "$GF_DIR"
pip install -e .[dev]

cd "$WORKING_DIR"
pip install $DEPENDENCIES
pip install tqdm nbconvert selenium webdriver-manager

pip freeze > "$WORKING_DIR"/pip_freeze.txt
python --version > "$WORKING_DIR"/python_version.txt

cp "$GF_DIR"/tests/integration/integration_tests.ipynb .
#jupyter nbconvert --execute ./integration_tests.ipynb --to notebook --output "$WORKING_DIR/output.ipynb"
python "$GF_DIR"/tests/integration/jupyter_driver.py --headless "$SERVICE" integration_tests.ipynb


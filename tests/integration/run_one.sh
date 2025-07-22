#!/usr/bin/env bash
set -e

WORKING_DIR=$1
OUTPUT_FILE=$2
PYTHON_VERSION=$3
SERVICE=$4
DEPENDENCIES=$5

do_run() {
  GF_DIR=$( readlink -f $( dirname "$0" )/../../ )

  mkdir -p "$WORKING_DIR"
  cd "$WORKING_DIR"

  pip install --upgrade pip
  pip install uv

  rm -rf venv/
  uv venv --python "$PYTHON_VERSION" venv/
  source venv/bin/activate

  cd "$GF_DIR"
  uv pip install -e .[dev]

  cd "$WORKING_DIR"
  uv pip install $DEPENDENCIES
  uv pip install tqdm nbconvert selenium webdriver-manager

  uv pip freeze > "$WORKING_DIR"/pip_freeze.txt
  python --version > "$WORKING_DIR"/python_version.txt

  cp "$GF_DIR"/tests/integration/integration_tests.ipynb .
  #jupyter nbconvert --execute ./integration_tests.ipynb --to notebook --output "$WORKING_DIR/output.ipynb"
  python "$GF_DIR"/tests/integration/jupyter_driver.py --headless "$SERVICE" integration_tests.ipynb

  python "$GF_DIR"/tests/integration/report.py "$( pwd )" report.xlsx detailed_report.xlsx --single
}

do_run 2>&1 | tee "$OUTPUT_FILE"

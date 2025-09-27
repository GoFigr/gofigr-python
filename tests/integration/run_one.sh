#!/usr/bin/env bash
set -e
set -o pipefail

WORKING_DIR=$1
OUTPUT_FILE=$2
PYTHON_VERSION=$3
SERVICE=$4
DEPENDENCIES=$5
DRIVER_ARGS=$6

do_run() {
  GF_DIR=$( readlink -f $( dirname "$0" )/../../ )

  if [ -e "$HOME"/.nvm/nvm.sh ]; then
    \. "$HOME/.nvm/nvm.sh"
  fi

  mkdir -p "$WORKING_DIR"
  cd "$WORKING_DIR"

  rm -rf venv/
  uv venv --python "$PYTHON_VERSION" venv/
  source venv/bin/activate

  cd "$GF_DIR"
  uv pip install -e .[dev]

  cd "$WORKING_DIR"
  cp -r "$GF_DIR"/tests/integration/environments .
  uv pip install $DEPENDENCIES
  uv pip install tqdm nbconvert selenium webdriver-manager

  uv pip freeze > "$WORKING_DIR"/pip_freeze.txt
  python --version > "$WORKING_DIR"/python_version.txt

  cp "$GF_DIR"/tests/integration/{integration_tests.ipynb,lite_tests.ipynb} .

  mv ./lite_tests.ipynb lite_tests.bak # otherwise Jupyter will open it automatically

  #jupyter nbconvert --execute ./integration_tests.ipynb --to notebook --output "$WORKING_DIR/output.ipynb"
  python "$GF_DIR"/tests/integration/jupyter_driver.py $DRIVER_ARGS "$SERVICE" integration_tests.ipynb

  mv ./integration_tests.ipynb integration_tests.bak # otherwise Jupyter will open it automatically
  mv ./lite_tests.bak lite_tests.ipynb
  rm ./*done
  python "$GF_DIR"/tests/integration/jupyter_driver.py $DRIVER_ARGS "$SERVICE" lite_tests.ipynb

  python "$GF_DIR"/tests/integration/report.py "$( pwd )" report.xlsx detailed_report.xlsx --single --name "integration_test.json"
  python "$GF_DIR"/tests/integration/report.py "$( pwd )" report_lite.xlsx detailed_report_lite.xlsx --single --name "lite_tests.json"
}

do_run 2>&1 | tee "$OUTPUT_FILE"

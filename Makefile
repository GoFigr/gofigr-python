.PHONY: build build-pyodide docs lint test test-dev test-local version

build:
	bash build.sh

build-pyodide:
	bash build_pyodide_wheel.sh

docs:
	bash make_docs.sh

lint:
	bash run_lints.sh

test:
	GF_TEST_API_URL=$${GF_TEST_API_URL:-https://api-dev.gofigr.io} venv/bin/pytest -v -s --tb=short --durations=0 $(if $(ARGS),$(ARGS),tests/)

test-dev:
	GF_TEST_API_URL=https://api-dev.gofigr.io venv/bin/pytest -v -s --tb=short --durations=0 $(if $(ARGS),$(ARGS),tests/)

test-local:
	GF_TEST_API_URL=http://localhost:8000 venv/bin/pytest -v -s --tb=short --durations=0 $(if $(ARGS),$(ARGS),tests/)

version:
	bumpver update --$(or $(filter patch minor major,$(word 2,$(MAKECMDGOALS))),patch)

patch minor major:
	@true

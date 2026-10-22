PYTHON ?= python3
SCHEDULE ?= 0
.PHONY: help install run test test-unit lint format clean
help:
	@echo 'install | run | test [SCHEDULE=1] | test-unit | lint | format | clean'
install:
	$(PYTHON) -m pip install -r requirements.txt
run:
	$(PYTHON) cryptoserver.py
test:
	SCHEDULE=$(SCHEDULE) $(PYTHON) tests/tests.py
test-unit:
	$(PYTHON) -m pytest -q
lint:
	$(PYTHON) -m ruff check .
	$(PYTHON) -m ruff format --check .
format:
	$(PYTHON) -m ruff check --fix .
	$(PYTHON) -m ruff format .
clean:
	$(PYTHON) -c "import pathlib, shutil; [shutil.rmtree(p) for p in pathlib.Path('.').rglob('__pycache__') if '.venv' not in p.parts]"
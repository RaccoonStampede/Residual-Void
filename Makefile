PYTHON ?= python3
PIP ?= $(PYTHON) -m pip
PYTEST ?= $(PYTHON) -m pytest

.PHONY: install test build smoke release-check

install:
	$(PIP) install -r requirements.txt

test:
	$(PYTEST) -q

build:
	$(PIP) install --upgrade build
	$(PYTHON) -m build

smoke:
	$(PIP) install -v .
	residual-void --version
	residual-void --demo

release-check: install test build smoke

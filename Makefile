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

smoke-live:
	$(PYTHON) smoke_test.py

smoke-live-url:
	@test -n "$(URL)" || (echo "Usage: make smoke-live-url URL=https://your-deployed-host" && exit 1)
	$(PYTHON) smoke_test.py --url "$(URL)"

release-check: install test build smoke smoke-live

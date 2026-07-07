# SPDX-FileCopyrightText: 2025 Sebastian Andersson <sebastian@bittr.nu>
#
# SPDX-License-Identifier: GPL-3.0-or-later

.SILENT:

VENV:=venv
VENV_TIMESTAMP:=$(VENV)/.timestamp
PIP:=$(VENV)/bin/pip3
BLACK:=$(VENV)/bin/black
PYLINT:=$(VENV)/bin/pylint
REUSE:=$(VENV)/bin/reuse

SRC=$(wildcard *.py lib/*.py)

help:
	@echo Available targets:
	@echo test - run the test suite.
	@echo fmt - formats the python files.
	@echo lint - check the python files with pylint.
	@echo clean - remove venv directory.

$(VENV_TIMESTAMP): requirements.txt requirements-dev.txt
	@echo Building $(VENV)
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip setuptools wheel
	$(PIP) install -r requirements-dev.txt
	touch $@

$(BLACK): $(VENV_TIMESTAMP)
	$(PIP) install black

$(PYLINT): $(VENV_TIMESTAMP)
	$(PIP) install pylint

$(REUSE): $(VENV_TIMESTAMP)
	$(PIP) install reuse

fmt: $(BLACK)
	$(BLACK) $(SRC)

lint: $(PYLINT)
	$(PYLINT) $(SRC)

test: $(VENV_TIMESTAMP)
	$(VENV)/bin/python -m pytest -q

reuse: $(REUSE)
	$(REUSE) lint

clean:
	@rm -rf $(VENV) 2>/dev/null

.PHONY: clean fmt lint reuse test

VENV   := .venv
PYTHON := $(VENV)/bin/python
PIP    := $(VENV)/bin/pip

.PHONY: dev test sync-agents clean data-init data-link help

$(PYTHON):
	python3 -m venv $(VENV)
	$(PIP) install -q -e ".[dev]"

dev: $(PYTHON)

test: $(PYTHON)
	$(PYTHON) -m pytest tests/ -v

sync-agents:
	python3 scripts/sync_agents.py

clean:
	rm -rf $(VENV) build/ *.egg-info/

data-init:
	mkdir -p data

data-link:
	@test -n "$(EXTERNAL)" || (echo "Usage: make data-link EXTERNAL=/path/to/external-drive"; exit 1)
	@if [ -d data ] && [ ! -L data ]; then \
		if [ -z "$$(ls -A data 2>/dev/null)" ]; then rm -rf data; \
		else echo "data/ exists and is not empty — move or remove its contents before linking"; exit 1; fi; \
	fi
	mkdir -p $(EXTERNAL)/$(notdir $(CURDIR))/data
	ln -sfn $(EXTERNAL)/$(notdir $(CURDIR))/data data

help:
	@echo "Development:"
	@echo "  make dev          — create .venv and install in editable mode"
	@echo "  make test         — run pytest"
	@echo "Agent rules:"
	@echo "  make sync-agents  — regenerate CLAUDE.md + AGENTS.md from CONTEXT.md"
	@echo "Maintenance:"
	@echo "  make clean        — remove .venv and build artefacts"
	@echo "  make data-init    — create data/ as a real local directory"
	@echo "  make data-link EXTERNAL=/path  — symlink data/ to an external drive"

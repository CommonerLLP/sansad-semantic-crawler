VENV   := .venv
PYTHON := $(VENV)/bin/python
PIP    := $(VENV)/bin/pip

.PHONY: dev test sync-agents clean help

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

help:
	@echo "Development:"
	@echo "  make dev          — create .venv and install in editable mode"
	@echo "  make test         — run pytest"
	@echo "Agent rules:"
	@echo "  make sync-agents  — regenerate CLAUDE.md + AGENTS.md from CONTEXT.md"
	@echo "Maintenance:"
	@echo "  make clean        — remove .venv and build artefacts"

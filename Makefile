.PHONY: setup dev test serve worker
PYTHON ?= python3

setup:
	$(PYTHON) -m venv .venv
	.venv/bin/python -m pip install -e ".[studio,test]"

dev:
	PYTHONPATH=src .venv/bin/python -m legacyai.studio.manage demo

serve:
	PYTHONPATH=src .venv/bin/python -m legacyai.studio.manage serve

worker:
	PYTHONPATH=src .venv/bin/python -m legacyai.studio.manage worker

test:
	PYTHONPATH=src .venv/bin/python -m pytest tests -q

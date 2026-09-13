.PHONY: instalar testes lint frontend servir seed coletar limpar tudo

VENV ?= .venv
PY := $(VENV)/bin/python

instalar:
	python3 -m venv $(VENV)
	$(VENV)/bin/pip install -e "backend[dev]"
	cd frontend && npm install

testes:
	$(PY) -m pytest backend/tests -q

lint:
	$(VENV)/bin/ruff check backend/src backend/tests

frontend:
	cd frontend && npm run build

seed:
	$(VENV)/bin/radar seed

servir:
	$(VENV)/bin/radar servir

coletar:
	$(VENV)/bin/radar coletar --todas

limpar:
	rm -rf radar.db data/raw data/docs frontend/dist
	find . -name __pycache__ -type d -prune -exec rm -rf {} +

# O que o CI roda.
tudo: lint testes frontend

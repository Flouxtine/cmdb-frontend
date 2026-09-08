PY := python3
VENV := .venv
PIP := $(VENV)/bin/pip
PYTEST := $(VENV)/bin/python -m pytest

.PHONY: venv install test run docker-build

venv:
	$(PY) -m venv $(VENV)

install: venv
	$(PIP) install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/

test:
	$(PYTEST) tests/ -q

run: install
	$(VENV)/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

docker-build:
	docker build -t opsscope:latest .

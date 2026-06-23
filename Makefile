IMAGE ?= k3sctl:latest

.PHONY: install test build run lint clean

install:
	pip install -e ".[dev]"

test:
	python -m pytest -q

build:
	docker build -t $(IMAGE) .

# Pasa flags extra con:  make run ARGS="--read-only"
run:
	./run.sh run $(ARGS)

clean:
	rm -rf build dist *.egg-info .pytest_cache
	find . -type d -name __pycache__ -exec rm -rf {} +

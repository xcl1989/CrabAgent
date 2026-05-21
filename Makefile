.PHONY: all install dev build frontend static clean distclean docker

all: build

frontend:
	cd frontend && npm ci && npm run build

static: frontend
	@mkdir -p src/crabagent/static
	cp -R frontend/dist/index.html frontend/dist/assets src/crabagent/static/

install: static
	pip install -e '.[serve,dev]'

dev: install

build: static
	pip install build
	python -m build

clean:
	rm -rf src/crabagent/static
	rm -rf frontend/dist

distclean: clean
	rm -rf *.egg-info
	rm -rf dist
	rm -rf .eggs

docker:
	docker compose build

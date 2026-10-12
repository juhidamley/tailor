.PHONY: help sync test test-server test-ext lint check serve ext

help:
	@echo "make test    pytest (server) + extension tests"
	@echo "make lint    ruff + mypy --strict on server/tailor"
	@echo "make check   verify Tectonic + claude CLI, warm the TeX cache"
	@echo "make serve   run the local server on 127.0.0.1:8765 (M6)"
	@echo "make ext     build the extension to extension/dist (M7)"

sync:
	uv sync

test: test-server test-ext

test-server:
	uv run pytest

# The extension arrives in M7; until then there is nothing to test.
test-ext:
	@if [ -f extension/package.json ]; then \
		cd extension && npm test; \
	else \
		echo "test-ext: no extension/ yet (M7), skipping"; \
	fi

lint:
	uv run ruff check server
	uv run ruff format --check server
	uv run mypy

check:
	uv run python -m tailor check --warm

serve:
	uv run python -m tailor serve

ext:
	@if [ -f extension/package.json ]; then \
		cd extension && npm run build; \
	else \
		echo "ext: no extension/ yet (M7)"; exit 2; \
	fi

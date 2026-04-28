# Agent Instructions

Flask web app that presents Ansible inventories as a CMDB (Configuration Management Database) webpage. See [README.md](README.md) for full project overview.

## Setup

```bash
pipx install poetry
poetry install
poetry shell
```

## Essential Commands

| Task                      | Command                                            |
| ------------------------- | -------------------------------------------------- |
| Run tests (with coverage) | `pytest`                                           |
| Lint                      | `ruff check ansibleinventorycmdb tests`            |
| Format                    | `ruff format ansibleinventorycmdb tests`           |
| Type check                | `mypy` and `pyright`                               |
| Dev server                | `flask --app ansibleinventorycmdb run --port 5000` |

## Architecture

| Module                                                                 | Role                                                                              |
| ---------------------------------------------------------------------- | --------------------------------------------------------------------------------- |
| [`ansibleinventorycmdb/__init__.py`](ansibleinventorycmdb/__init__.py) | Flask app factory (`create_app()`)                                                |
| [`ansibleinventorycmdb/bp_cmdb.py`](ansibleinventorycmdb/bp_cmdb.py)   | Blueprint: routes + CMDB lifecycle + background refresh thread                    |
| [`ansibleinventorycmdb/cmdb.py`](ansibleinventorycmdb/cmdb.py)         | `AnsibleCMDB`: fetches inventory URLs, parses hosts/groups/vars, pickle URL cache |
| [`ansibleinventorycmdb/config.py`](ansibleinventorycmdb/config.py)     | `AnsibleInventoryCmdbConfig`: YAML config loader, dict-like interface             |
| [`ansibleinventorycmdb/logger.py`](ansibleinventorycmdb/logger.py)     | Custom logger with TRACE level (5); use `get_logger(__name__)` per module         |

Templates use `.html.j2` extension (Jinja2). Static assets (CSS, JS, fonts) are in [`ansibleinventorycmdb/static/`](ansibleinventorycmdb/static/).

## Configuration

Config file: `instance/config.yml`. See [instance/config.yml](instance/config.yml) for the canonical example. Key sections: `cmdb` (inventory URLs + schema_mapping), `logging`, `flask`.

`AnsibleInventoryCmdbConfig` validates that `TESTING=true` only when `tmp_path` is used — this prevents tests from writing to production paths.

## Testing

```bash
pytest                   # runs all tests + coverage
pytest -k test_name      # single test
```

- **All HTTP requests are mocked** via an auto-use fixture in [`tests/conftest.py`](tests/conftest.py) — add new URLs to the mock list when adding inventory URL tests.
- Test configs live in [`tests/configs/`](tests/configs/); test inventories in [`tests/inventories/`](tests/inventories/).
- Always pass `tmp_path` when constructing `AnsibleInventoryCmdbConfig` in tests (required by config validation).
- Tests run in random order (`pytest-random-order`) and are checked for pollution (`detect-test-pollution`).

## Code Conventions

- **Type hints** required on all functions; enforced by ruff (`ANN` rules, relaxed in tests).
- **Google-style docstrings** required on all modules, classes, and public functions.
- **Double quotes**, max line length **120**.
- `ruff` is configured with `select = ["ALL"]` and selective ignores — run `ruff check` before committing.
- Module logger: `logger = get_logger(__name__)` at module level.

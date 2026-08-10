# ansibleinventorycmdb

[![Check](https://github.com/kism/ansible-inventory-cmdb/actions/workflows/check.yml/badge.svg)](https://github.com/kism/ansible-inventory-cmdb/actions/workflows/check.ym)
[![Type](https://github.com/kism/ansible-inventory-cmdb/actions/workflows/check_types.yml/badge.svg)](https://github.com/kism/ansible-inventory-cmdb/actions/workflows/check_types.yml)
[![Test](https://github.com/kism/ansible-inventory-cmdb/actions/workflows/test.yml/badge.svg)](https://github.com/kism/ansible-inventory-cmdb/actions/workflows/test.yml)
[![codecov](https://codecov.io/gh/kism/ansible-inventory-cmdb/graph/badge.svg?token=yA1IpJESD1)](https://codecov.io/gh/kism/ansible-inventory-cmdb)

Presents an internet hosted Ansible inventory as a nice webpage. No database, the inventory is fetched over HTTP
into memory. Three ways to run it: a FastAPI web app that refreshes every 6 hours, a static site rendered to a
directory, or a cron-triggered Cloudflare Worker that renders into an R2 bucket.

## Prerequisites

Install uv <https://docs.astral.sh/uv/getting-started/installation/>

## Run

The web server is an extra, `--extra server`. Without it you get the two serverless modes: the static site renderer
and the Cloudflare Worker (see below).

### Run Dev

```bash
uv sync --extra server
uv run uvicorn ansibleinventorycmdb:create_app --factory --reload --port 5100
```

### Run Prod

```bash
uv sync --extra server --no-dev
.venv/bin/uvicorn ansibleinventorycmdb:create_app \
    --factory \
    --host 127.0.0.1 \
    --port 5000 \
    --workers 1 \
    --proxy-headers \
    --forwarded-allow-ips '*'
```

`--workers 1` is not optional. Each worker builds and holds its own full copy of the inventory and runs its own
refresh thread.

There is also a console script, `ansibleinventorycmdb`, which serves on `AIC_HOST` (default `127.0.0.1`) and
`AIC_PORT` (default `5100`).

### Run without a server

Render the whole site to a directory:

```bash
uv sync
uv run ansibleinventorycmdb-generate ./out
```

Or let a cron-triggered Python Worker render every page into a public Cloudflare R2 bucket once a day. See
[README_Wrangler.md](README_Wrangler.md).

## Configuration

Config is read from the first of these that exists:

1. `<instance path>/config.yml`
2. `~/.config/ansibleinventorycmdb/config.yml`
3. `/etc/ansibleinventorycmdb/config.yml`

The instance path defaults to `./instance` and can be overridden with `AIC_INSTANCE_PATH`. It also holds
`cmdb_dump.yml` (the parsed inventory) and `url_cache.pkl` (the fetched YAML). If no config file is found anywhere,
one is written with defaults at location 1.

```yaml
cmdb:
  kism_main: # An arbitrary name for the inventory
    inventory_url: https://raw.githubusercontent.com/kism/ansible-playbooks/refs/heads/main/inventory/main.yml
    schema_mapping: # Ansible var -> column heading on the inventory page
      ansible_host: Hostname
      ansible_host_description: Description
logging:
  level: INFO
  path: "" # Empty means log to console only
```

Config is validated with pydantic and unknown keys are rejected, so a typo fails at startup rather than being
silently ignored.

# ansibleinventorycmdb

[![Check](https://github.com/kism/ansible-inventory-cmdb/actions/workflows/check.yml/badge.svg)](https://github.com/kism/ansible-inventory-cmdb/actions/workflows/check.ym)
[![Type](https://github.com/kism/ansible-inventory-cmdb/actions/workflows/check_types.yml/badge.svg)](https://github.com/kism/ansible-inventory-cmdb/actions/workflows/check_types.yml)
[![Test](https://github.com/kism/ansible-inventory-cmdb/actions/workflows/test.yml/badge.svg)](https://github.com/kism/ansible-inventory-cmdb/actions/workflows/test.yml)
[![codecov](https://codecov.io/gh/kism/ansible-inventory-cmdb/graph/badge.svg?token=yA1IpJESD1)](https://codecov.io/gh/kism/ansible-inventory-cmdb)

Webapp that presents an internet hosted Ansible inventory as a nice webpage. FastAPI, no database, the inventory is
fetched over HTTP into memory and refreshed every 6 hours.

## Prerequisites

Install uv <https://docs.astral.sh/uv/getting-started/installation/>

## Run

### Run Dev

```bash
uv sync
uv run uvicorn ansibleinventorycmdb:create_app --factory --reload --port 5100
```

### Run Prod

```bash
uv sync --no-dev
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

### Run as a Cloudflare Worker

An alternate run mode: instead of a server, a cron-triggered Python Worker builds the CMDB once a day and writes
every page into an R2 bucket, which serves them as static files. Same code, same templates — see
[`site.py`](src/ansibleinventorycmdb/site.py), which the web app and the Worker both render through.

Requires **Workers Paid**. Building the real inventory takes ~75 subrequests (one per host and group var file,
times two paths), over the free plan's cap of 50.

```bash
wrangler r2 bucket create ansible-inventory-cmdb   # then enable public access on it in the dashboard
cd worker
$EDITOR src/config.yml                             # same schema as instance/config.yml
uv run pywrangler dev                              # then trigger a build, see below
uv run pywrangler deploy
```

Cron Triggers don't fire during local development, so trigger a build by hand:

```bash
curl http://localhost:8787/cdn-cgi/handler/scheduled
```

The bucket has no index document, so the site's entry point is **`/index.html`**, not `/`. Every page is written
as `<path>/index.html` and linked that way. If you put a custom domain in front of the bucket, a redirect rule
from `/` to `/index.html` tidies that up.

To render the same site to a local directory instead:

```bash
uv run ansibleinventorycmdb-generate ./out
```

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

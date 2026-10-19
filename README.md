# ansibleinventorycmdb

[![Lint](https://github.com/kism/ansible-inventory-cmdb/actions/workflows/lint.yml/badge.svg)](https://github.com/kism/ansible-inventory-cmdb/actions/workflows/lint.yml)
[![Type Check](https://github.com/kism/ansible-inventory-cmdb/actions/workflows/check_types.yml/badge.svg)](https://github.com/kism/ansible-inventory-cmdb/actions/workflows/check_types.yml)
[![Test](https://github.com/kism/ansible-inventory-cmdb/actions/workflows/test.yml/badge.svg)](https://github.com/kism/ansible-inventory-cmdb/actions/workflows/test.yml)
[![Build](https://github.com/kism/ansible-inventory-cmdb/actions/workflows/build.yml/badge.svg)](https://github.com/kism/ansible-inventory-cmdb/actions/workflows/build.yml)
[![codecov](https://codecov.io/gh/kism/ansible-inventory-cmdb/graph/badge.svg?token=yA1IpJESD1)](https://codecov.io/gh/kism/ansible-inventory-cmdb)

Presents an internet hosted Ansible inventory as a nice webpage. No database, the inventory is fetched over HTTP
and rendered into a small JSON API, which a TypeScript frontend turns into pages in the browser. Two ways to host
it, serving the same API and the same frontend:

- a FastAPI web app, which keeps the API in memory and rebuilds it every 6 hours, or
- a cron-triggered Cloudflare Worker, which writes the API into an R2 bucket once a day and serves the frontend as
  static assets. See [README_Wrangler.md](README_Wrangler.md).

## Prerequisites

- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- Node, the version in `.nvmrc` (`nvm use`), and [pnpm](https://pnpm.io/installation) (`npm i -g pnpm`), to build
  the frontend. The pnpm version is pinned in `packageManager` in `package.json`

## Run

The web server is an extra, `--extra server`. Without it you get what the Cloudflare Worker needs, and nothing
else.

### Run Dev

```bash
uv sync --extra server
pnpm install && pnpm build   # the frontend, into frontend/dist, which the web app serves at /
uv run uvicorn ansibleinventorycmdb.app:create_app --factory --reload --port 5100
```

Working on the frontend? Leave the web app running and use `pnpm dev` instead of `pnpm build`: Vite serves
the frontend with hot reload on http://localhost:5173 and proxies `/api` to the web app on port 5100.

### Run Prod

```bash
uv sync --extra server --no-dev
pnpm install && pnpm build
.venv/bin/uvicorn ansibleinventorycmdb.app:create_app \
    --factory \
    --host 127.0.0.1 \
    --port 5000 \
    --workers 1 \
    --proxy-headers \
    --forwarded-allow-ips '*'
```

`--workers 1` is not optional. Each worker builds and holds its own full copy of the inventory and runs its own
refresh thread.

The frontend is read from `frontend/dist` in the checkout, so run the server from one. Without a build there the
server logs a warning and serves the API alone.

There is also a console script, `ansibleinventorycmdb`, which serves on `AIC_HOST` (default `127.0.0.1`) and
`AIC_PORT` (default `5100`).

Set `AIC_COMMIT_SHA` to have the page footer name the commit the deployment was built from — there is no `.git`
to read one out of once the package is installed. `pnpm run deploy` does the equivalent for the Cloudflare Worker,
passing `--var COMMIT_SHA:$(git rev-parse --short HEAD)`.

### Endpoints

| Path            | What                                                                                   |
| --------------- | -------------------------------------------------------------------------------------- |
| `/`, `/inventory/...` | The frontend. Any path that isn't a file gets the app, which routes on the URL    |
| `/api/<key>`    | The API: `inventories.json`, `inventory/<name>.json`, and a `.json` per host and group |
| `/api/inventory/<name>/group/<group>/hosts.json` | Hostname to vars for every host in a group, `all` included |
| `/status`       | When the API was last built, 503 once the next refresh is more than two hours overdue  |
| `/health`       | The version                                                                            |

The Worker serves the same API keys from its bucket's domain, and the same `/status`.

### Run without a server

Let a cron-triggered Python Worker write the API into a public Cloudflare R2 bucket once a day, with the frontend
as the Worker's static assets. See [README_Wrangler.md](README_Wrangler.md) to deploy it, and
[README_Wrangler_dev.md](README_Wrangler_dev.md) to work on it.

## Configuration

Config is read from the first of these that exists:

1. `<instance path>/config.yml`
2. `~/.config/ansibleinventorycmdb/config.yml`
3. `/etc/ansibleinventorycmdb/config.yml`

The instance path defaults to `./instance` and can be overridden with `AIC_INSTANCE_PATH`. Config is the only
thing kept there — the inventory lives in memory and is re-fetched on every build. If no config file is found
anywhere, one is written with defaults at location 1.

The Cloudflare Worker is the exception: it has no instance path at runtime, so it reads
[`src/config.yml`](src/config.yml), which is tracked and bundled with it. Same schema.

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

## Development

```bash
uv sync && pnpm install
pnpm lint                    # biome, ruff check, ruff format --check (pnpm format to fix)
pnpm typecheck               # ty, and tsc on the frontend
pnpm test                    # vitest, then pytest; args go to pytest: pnpm test -k name
pnpm build                   # the frontend, into frontend/dist
pnpm coverage                # both, under coverage
pnpm check_worker            # boots the Worker under Pyodide, see README_Wrangler_dev.md
```

`pnpm check` runs everything the workflows do, in order, and formats while it's at it.

## Workflows

The `.github` folder has one workflow per check, so a failing badge tells you what broke:

| Workflow          | Runs                                                       |
| ----------------- | ---------------------------------------------------------- |
| `lint.yml`        | Ruff and Biome                                             |
| `check_types.yml` | ty                                                         |
| `test.yml`        | vitest and pytest with coverage, uploaded to Codecov       |
| `build.yml`       | `pnpm check_worker`, and the frontend's tsc and build |

Dependabot PRs are merged automatically once checks pass (`dependabot_automerge.yml`).

### Codecov

The Test workflow uploads with OIDC, so no token secret is needed.

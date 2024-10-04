# ansibleinventorycmdb

Webapp that presents an internet hosted Ansible inventory as a nice webpage

Config, check what gets created in the instance folder

## Prerequisites

Install pipx <https://pipx.pypa.io/stable/>

Install poetry with pipx `pipx install poetry`

## Run

### Run Dev

```bash
poetry install
poetry shell
flask --app ansibleinventorycmdb run --port 5000
```

### Run Prod

```bash
poetry install --only main
.venv/bin/waitress-serve \
    --listen "127.0.0.1:5000" \
    --trusted-proxy '*' \
    --trusted-proxy-headers 'x-forwarded-for x-forwarded-proto x-forwarded-port' \
    --log-untrusted-proxy-headers \
    --clear-untrusted-proxy-headers \
    --threads 4 \
    --call ansibleinventorycmdb:create_app
```

## Todo

- ~~Cleanup logging~~
- ~~Use instance path properly~~
- ~~Refresh every X hours~~
- ~~Use YAML~~
- ~~Write real readme~~
- ~~fix that text block issue in the vars yaml~~

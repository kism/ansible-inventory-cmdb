"""Present Ansible inventories as a CMDB, either as a web app or as a static site.

Deliberately empty of imports. `create_app` lives in `app.py` and is referenced as
`ansibleinventorycmdb.app:create_app`, so that importing this package — as the Cloudflare Worker in `src/entry.py`
does, for `cmdb` and `site` — pulls in no FastAPI. It isn't even installed unless you `uv sync --extra server`.
"""

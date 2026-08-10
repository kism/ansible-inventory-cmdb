"""Cloudflare Worker: render the CMDB to a public R2 bucket on a cron trigger.

No fetch handler. The Worker only writes objects, R2 serves them. To trigger a build by hand during
`pywrangler dev`, curl http://localhost:8787/__scheduled
"""

from pathlib import Path

import yaml
from ansibleinventorycmdb.cmdb import AnsibleCMDB
from ansibleinventorycmdb.config import Config
from ansibleinventorycmdb.logger import LoggingConfig, get_logger, setup_logger
from ansibleinventorycmdb.site import render_site
from workers import WorkerEntrypoint, fetch

# Bundled with the Worker, since there is no instance path to read a config from.
CONFIG = Config(**yaml.safe_load((Path(__file__).parent / "config.yml").read_text()))

setup_logger(CONFIG.logging)
logger = get_logger(__name__)


async def fetch_text(url: str) -> str | None:
    """Fetch a URL with the Workers runtime's fetch. aiohttp can't do it here: no sockets, no ssl module."""
    response = await fetch(url)
    return await response.text() if response.ok else None


class Default(WorkerEntrypoint):
    """The Worker's entrypoint."""

    async def scheduled(self, controller, env, ctx) -> None:  # noqa: ANN001, ARG002 Signature is the runtime's
        """Build the CMDB and write every page to R2. All four parameters are required by the runtime."""
        cmdb = AnsibleCMDB(CONFIG.cmdb)  # No instance path: Workers have no writable filesystem
        await cmdb.build(fetch_text)

        count = 0
        for key, body, content_type in render_site(cmdb.inventories, CONFIG.cmdb):
            await self.env.CMDB_BUCKET.put(key, body, httpMetadata={"contentType": content_type})
            count += 1

        logger.info("Wrote %s objects to R2", count)

"""Cloudflare Worker: render the CMDB to a public R2 bucket.

Normally driven by the cron trigger in wrangler.jsonc. The fetch handler exists only so a build can be run
on demand — a deployed cron trigger cannot be fired by hand, so without it the first build after a deploy waits
for the next scheduled run.

To trigger a build during `pywrangler dev`, curl http://localhost:8787/cdn-cgi/handler/scheduled
"""

import hmac
from pathlib import Path

import yaml
from workers import Response, WorkerEntrypoint, fetch

from ansibleinventorycmdb.cmdb import AnsibleCMDB
from ansibleinventorycmdb.config import Config
from ansibleinventorycmdb.logger import get_logger, setup_logger
from ansibleinventorycmdb.site import render_site

# Bundled with the Worker, since there is no instance path to read a config from.
CONFIG = Config(**yaml.safe_load((Path(__file__).parent / "config.yml").read_text()))

setup_logger(CONFIG.logging)
logger = get_logger(__name__)


async def fetch_text(url: str) -> str | None:
    """Fetch a URL with the Workers runtime's fetch, rather than cmdb.py's default httpx client."""
    response = await fetch(url)
    return await response.text() if response.ok else None


class Default(WorkerEntrypoint):
    """The Worker's entrypoint."""

    async def scheduled(self, controller, env, ctx) -> None:  # noqa: ANN001, ARG002 Signature is the runtime's
        """Build the CMDB and write every page to R2. All four parameters are required by the runtime."""
        await self._build_and_upload()

    async def fetch(self, request) -> Response:  # noqa: ANN001 The runtime passes a JS Request
        """Run a build on demand. Requires the BUILD_TOKEN secret as a bearer token.

        The workers.dev URL is public, and a build costs ~75 requests against whatever hosts the inventory, so an
        unauthenticated endpoint here would be a free way to hammer someone else's server. Fails closed: with no
        BUILD_TOKEN configured there is no way in.
        """
        expected = getattr(self.env, "BUILD_TOKEN", None)
        presented = request.headers.get("authorization") or ""

        # 404 rather than 403, so an unauthenticated caller can't tell the endpoint apart from a missing one.
        if not expected or not hmac.compare_digest(presented, f"Bearer {expected}"):
            logger.warning("Rejected an unauthenticated build request")
            return Response("Not found", status=404)

        count = await self._build_and_upload()
        return Response(f"Wrote {count} objects\n")

    async def _build_and_upload(self) -> int:
        """Build the CMDB and PUT every rendered page into R2. Returns the number of objects written."""
        cmdb = AnsibleCMDB(CONFIG.cmdb)  # No instance path: Workers have no writable filesystem
        await cmdb.build(fetch_text)

        count = 0
        for key, body, content_type in render_site(cmdb.inventories, CONFIG.cmdb):
            await self.env.CMDB_BUCKET.put(key, body, httpMetadata={"contentType": content_type})
            count += 1

        logger.info("Wrote %s objects to R2", count)
        return count

"""Cloudflare Worker: render the CMDB to a public R2 bucket.

Normally driven by the cron trigger in wrangler.jsonc. The fetch handler serves two paths: `/refresh` exists
so a build can be run on demand — a deployed cron trigger cannot be fired by hand, so without it the first build
after a deploy waits for the next scheduled run — and `/status` reports on the last run. Everything else 404s.

To trigger a build during `pywrangler dev`, curl http://localhost:8787/cdn-cgi/handler/scheduled
"""

import hmac
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import yaml
from workers import Response, WorkerEntrypoint, fetch

from ansibleinventorycmdb.cmdb import AnsibleCMDB, github_zip_fetcher
from ansibleinventorycmdb.config import Config
from ansibleinventorycmdb.constants import COMMIT_SHA_ENV_VAR
from ansibleinventorycmdb.logger import get_logger, setup_logger
from ansibleinventorycmdb.site import render_site

# src/config.yml is a symlink to instance/config.yml, so there is only ever one config file. Workers have no
# instance path to read one from at runtime, so it is bundled (wrangler resolves the symlink at bundle time).
CONFIG = Config(**yaml.safe_load((Path(__file__).parent / "config.yml").read_text()))

setup_logger(CONFIG.logging)
logger = get_logger(__name__)

# The cron runs daily, so anything past a day plus a couple of hours of slack means a run was missed or failed.
STALE_AFTER_SECONDS = 26 * 60 * 60


async def fetch_bytes(url: str) -> bytes | None:
    """Fetch a URL with the Workers runtime's fetch, rather than cmdb.py's default httpx client.

    Bytes rather than text because github_zip_fetcher, which this is handed to, pulls down repo zips.
    """
    response = await fetch(url)
    return await response.bytes() if response.ok else None


class Default(WorkerEntrypoint):
    """The Worker's entrypoint."""

    async def scheduled(self, controller, env, ctx) -> None:  # noqa: ANN001, ARG002 Signature is the runtime's
        """Build the CMDB and write every page to R2. All four parameters are required by the runtime."""
        await self._build_and_upload()

    async def fetch(self, request) -> Response:  # noqa: ANN001 The runtime passes a JS Request
        """Rebuild the bucket at /refresh, or report on the last run at /status. /refresh needs BUILD_TOKEN.

        The workers.dev URL is public, and a build pulls a whole repo down from whoever hosts the inventory, so an
        unauthenticated endpoint here would be a free way to hammer someone else's server. Fails closed: with no
        BUILD_TOKEN configured there is no way in.

        `?token=` is there because nothing in the Cloudflare dashboard can fire a deployed cron trigger, or send
        an Authorization header. A URL is the only trigger you can click, so the query string is the browser's
        way in. Both forms compare in constant time; encode() because compare_digest rejects non-ASCII str.
        """
        url = urlparse(request.url)
        if url.path == "/status":
            return await self._status()

        # Same 404 as a bad token, for the same reason: nothing here should hint at what does exist.
        if url.path != "/refresh":
            return Response("Not found", status=404)

        expected = getattr(self.env, "BUILD_TOKEN", None)
        presented = request.headers.get("authorization") or ""
        in_url = parse_qs(url.query).get("token", [""])[0]

        # 404 rather than 403, so an unauthenticated caller can't tell the endpoint apart from a missing one.
        if not expected or not (
            hmac.compare_digest(presented.encode(), f"Bearer {expected}".encode())
            or hmac.compare_digest(in_url.encode(), expected.encode())
        ):
            logger.warning("Rejected an unauthenticated build request")
            return Response("Not found", status=404)

        count = await self._build_and_upload()
        return Response(f"Wrote {count} objects\n")

    async def _status(self) -> Response:
        """Report when the last build landed, as JSON. One R2 head request, no stored state of its own.

        The bucket already records this: every build rewrites index.html, so its upload time *is* the last
        successful run. A failed build writes nothing, which shows up here as an age that keeps growing — the
        thing worth alerting on either way. Recording failures as well would mean writing a status object on
        every run, and it would not answer a different question.

        Unauthenticated, unlike the build path: the bucket is public, so this leaks nothing a HEAD on the site
        itself wouldn't, and it costs one Cloudflare-internal request rather than a repo download. Stale answers
        503 so a plain uptime monitor can watch the URL without parsing the body.
        """
        page = await self.env.CMDB_BUCKET.head("index.html")
        # The binding hands `uploaded` over as a datetime. R2 records it in UTC, but the object comes through
        # naive, and subtracting that from an aware now() raises — so say so rather than reading it as local time.
        uploaded = None if page is None else page.uploaded.replace(tzinfo=UTC)
        age = None if uploaded is None else round((datetime.now(UTC) - uploaded).total_seconds())
        fresh = age is not None and age < STALE_AFTER_SECONDS

        body = {
            "ok": fresh,
            "last_build": None if uploaded is None else uploaded.isoformat(),
            "age_seconds": age,
            "stale_after_seconds": STALE_AFTER_SECONDS,
        }
        return Response(
            json.dumps(body) + "\n",
            status=200 if fresh else 503,
            headers={"content-type": "application/json"},
        )

    async def _build_and_upload(self) -> int:
        """Build the CMDB and PUT every rendered page into R2. Returns the number of objects written."""
        # constants.version_string() reads this from the environment, which is the only channel all three modes
        # share. Set here rather than at import: a wrangler var only exists on `env`, which the runtime hands to
        # a handler. Both handlers funnel through here, so it is always set before render_site() reads it.
        os.environ[COMMIT_SHA_ENV_VAR] = getattr(self.env, "COMMIT_SHA", "") or ""

        cmdb = AnsibleCMDB(CONFIG.cmdb)  # No instance path: Workers have no writable filesystem
        # One zip per repo, not one request per file: the free plan allows 50 external subrequests per invocation
        # and a build needs ~75. The R2 puts below come out of a separate, larger budget.
        await cmdb.build(github_zip_fetcher(fetch_bytes))

        count = 0
        for key, body, content_type in render_site(cmdb.inventories, CONFIG.cmdb, cmdb.built_at):
            await self.env.CMDB_BUCKET.put(key, body, httpMetadata={"contentType": content_type})
            count += 1

        logger.info("Wrote %s objects to R2", count)
        return count

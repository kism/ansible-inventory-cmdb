"""Cloudflare Worker: build the CMDB's JSON API into a public R2 bucket.

The Cloudflare half of the two hosts; the web app (app.py) is the other. Both build through api.build_api, so the
bucket holds exactly the objects the web app serves under /api/. The frontend is not this file's business: it's
the Worker's static assets (wrangler.jsonc), served without this code running.

Normally driven by the cron trigger in wrangler.jsonc. The fetch handler serves two paths: `/refresh` exists
so a build can be run on demand — a deployed cron trigger cannot be fired by hand, so without it the first build
after a deploy waits for the next scheduled run — and `/status` reports on the last run. Everything else 404s.

To trigger a build during `pywrangler dev`, curl http://localhost:8787/cdn-cgi/handler/scheduled
"""

import hmac
import json
import logging
import os
from datetime import UTC
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import yaml
from workers import Response, WorkerEntrypoint, fetch

from ansibleinventorycmdb.api import api_status, build_api
from ansibleinventorycmdb.cmdb import github_zip_fetcher
from ansibleinventorycmdb.config import Config
from ansibleinventorycmdb.constants import COMMIT_SHA_ENV_VAR
from ansibleinventorycmdb.logger import setup_logger

# Read the bundled config.yml rather than config.load_config(): a Worker has no instance path, and no writable
# filesystem for load_config's write-the-defaults fallback. src/config.yml is tracked, so the bundle always has one.
CONFIG = Config(**yaml.safe_load((Path(__file__).parent / "config.yml").read_text()))

setup_logger(CONFIG.logging)
logger = logging.getLogger(__name__)

# The cron runs daily, so anything past a day plus a couple of hours of slack means a run was missed or failed.
STALE_AFTER_SECONDS = 26 * 60 * 60

# Every build rewrites this one, so its upload time is the last successful run. See _status.
INDEX_KEY = "inventories.json"


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

        The bucket already records this: every build rewrites INDEX_KEY, so its upload time *is* the last
        successful run. A failed build writes nothing, which shows up here as an age that keeps growing — the
        thing worth alerting on either way. Recording failures as well would mean writing a status object on
        every run, and it would not answer a different question.

        Unauthenticated, unlike the build path: the bucket is public, so this leaks nothing a HEAD on the API
        itself wouldn't, and it costs one Cloudflare-internal request rather than a repo download. Stale answers
        503 so a plain uptime monitor can watch the URL without parsing the body. Same body as the web app's.
        """
        index = await self.env.CMDB_BUCKET.head(INDEX_KEY)
        # The binding hands `uploaded` over as a datetime. R2 records it in UTC, but the object comes through
        # naive, and subtracting that from an aware now() raises — so say so rather than reading it as local time.
        body = api_status(None if index is None else index.uploaded.replace(tzinfo=UTC), STALE_AFTER_SECONDS)
        return Response(
            json.dumps(body) + "\n",
            status=200 if body["ok"] else 503,
            headers={"content-type": "application/json"},
        )

    async def _build_and_upload(self) -> int:
        """Build the API, PUT every object into R2, and delete whatever the build didn't write.

        Returns the number of objects written.
        """
        # constants.version_string() reads this from the environment, which is the only channel both hosts
        # share. Set here rather than at import: a wrangler var only exists on `env`, which the runtime hands to
        # a handler. Both handlers funnel through here, so it is always set before build_api() reads it.
        os.environ[COMMIT_SHA_ENV_VAR] = getattr(self.env, "COMMIT_SHA", "") or ""

        # One zip per repo, not one request per file: the free plan allows 50 external subrequests per invocation
        # and a build needs ~75. The R2 calls below come out of a separate, larger budget.
        objects = await build_api(CONFIG.cmdb, github_zip_fetcher(fetch_bytes))

        for key, body in objects.items():
            await self.env.CMDB_BUCKET.put(key, body, httpMetadata={"contentType": "application/json"})
        logger.info("Wrote %s objects to R2", len(objects))

        await self._prune(objects)
        return len(objects)

    async def _prune(self, keep: dict[str, bytes]) -> None:
        """Delete every object in the bucket that this build didn't write.

        A host dropped from the inventory would otherwise keep its JSON in the bucket, still served, forever.
        Runs after the puts, so a build that died partway has already returned and deleted nothing.
        """
        stale: list[str] = []
        cursor = None
        while True:
            # A plain JS object comes back as a dict; the R2Object entries in it keep attribute access.
            listed = await (self.env.CMDB_BUCKET.list(cursor=cursor) if cursor else self.env.CMDB_BUCKET.list())
            stale += [obj.key for obj in listed["objects"] if obj.key not in keep]
            if not listed["truncated"]:
                break
            cursor = listed["cursor"]

        # delete() takes up to 1000 keys a call.
        for start in range(0, len(stale), 1000):
            await self.env.CMDB_BUCKET.delete(stale[start : start + 1000])
        if stale:
            logger.info("Deleted %s stale objects from R2", len(stale))

"""Tests github_zip_fetcher, the one-subrequest-per-repo fetcher the Cloudflare Worker builds with."""

import asyncio
import io
import zipfile

from ansibleinventorycmdb.cmdb import github_zip_fetcher

RAW = "https://raw.githubusercontent.com/someone/playbooks/refs/heads/main"


def make_zip(files: dict[str, str], root: str = "playbooks-main") -> bytes:
    """A repo zip shaped the way codeload.github.com serves one: everything under one directory."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for path, body in files.items():
            archive.writestr(f"{root}/{path}", body)
    return buffer.getvalue()


def fetcher_over(responses: dict[str, bytes | None]) -> tuple:
    """A fetcher backed by a fixed url -> body mapping, plus the list of URLs it was actually asked for."""
    requested: list[str] = []

    async def fetch_bytes(url: str) -> bytes | None:
        requested.append(url)
        return responses.get(url)

    return github_zip_fetcher(fetch_bytes), requested


def test_serves_files_from_one_zip():
    """TEST: Every file in the repo comes out of a single archive request, and a missing one is None."""
    zip_body = make_zip({"inventory/main.yml": "groupone:\n", "inventory/host_vars/hostone.yml": "a: 1\n"})
    fetch_text, requested = fetcher_over(
        {"https://codeload.github.com/someone/playbooks/zip/refs/heads/main": zip_body}
    )

    async def run():
        return [
            await fetch_text(f"{RAW}/inventory/main.yml"),
            await fetch_text(f"{RAW}/inventory/host_vars/hostone.yml"),
            await fetch_text(f"{RAW}/host_vars/hostone.yml"),  # Not in the repo, the normal case for a vars probe
        ]

    assert asyncio.run(run()) == ["groupone:\n", "a: 1\n", None]
    assert requested == ["https://codeload.github.com/someone/playbooks/zip/refs/heads/main"]


def test_falls_back_to_per_file_requests():
    """TEST: A non-GitHub URL, and a repo whose zip won't download, are fetched a file at a time."""
    elsewhere = "https://git.example.com/inventory/main.yml"
    fetch_text, requested = fetcher_over({elsewhere: b"groupone:\n", f"{RAW}/inventory/main.yml": b"grouptwo:\n"})

    async def run():
        return [await fetch_text(elsewhere), await fetch_text(f"{RAW}/inventory/main.yml")]

    assert asyncio.run(run()) == ["groupone:\n", "grouptwo:\n"]
    assert requested.count("https://codeload.github.com/someone/playbooks/zip/refs/heads/main") == 1

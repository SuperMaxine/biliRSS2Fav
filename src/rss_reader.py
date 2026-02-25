from __future__ import annotations

import asyncio
import logging
import re
from typing import Iterable
from urllib.parse import unquote

import feedparser
from bilibili_api.utils.aid_bvid_transformer import bvid2aid

LOGGER = logging.getLogger(__name__)

BV_PATTERN = re.compile(r"(BV[0-9A-Za-z]{10})")
AV_PATTERN = re.compile(r"(?:^|/)(?:av|AV)(\d+)(?:$|[/?#])")


def _iter_entry_links(entry: object) -> Iterable[str]:
    if isinstance(entry, dict):
        for key in ("link", "id", "guid", "title"):
            value = entry.get(key)
            if isinstance(value, str) and value:
                yield value
    else:
        for key in ("link", "id", "guid", "title"):
            value = getattr(entry, key, None)
            if isinstance(value, str) and value:
                yield value


def extract_aid_from_text(value: str) -> int | None:
    text = unquote(value)
    bv_match = BV_PATTERN.search(text)
    if bv_match:
        return int(bvid2aid(bv_match.group(1)))
    av_match = AV_PATTERN.search(text)
    if av_match:
        return int(av_match.group(1))
    return None


def _build_fetch_rss_command(url: str, timeout: int) -> list[str]:
    user_agent = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/132.0.0.0 Safari/537.36"
    )
    command = [
        "curl",
        "--fail",
        "--silent",
        "--show-error",
        "--location",
        "--max-time",
        str(timeout),
        "-H",
        f"User-Agent: {user_agent}",
    ]
    command.append(url)
    return command


async def fetch_rss_xml(url: str, sessdata: str | None = None, timeout: int = 20) -> str:
    command = _build_fetch_rss_command(url=url, timeout=timeout)
    curl_config = None
    if sessdata:
        # Pass cookie through stdin config to avoid exposing it in process args.
        curl_config = f'cookie = "SESSDATA={sessdata}"\n'.encode("utf-8")
        command.extend(["--config", "-"])
    process = await asyncio.create_subprocess_exec(
        *command,
        stdin=asyncio.subprocess.PIPE if curl_config else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(input=curl_config),
            timeout=timeout + 5,
        )
    except asyncio.TimeoutError:
        process.kill()
        await process.communicate()
        raise TimeoutError(f"fetch_rss timeout after {timeout}s")
    if process.returncode != 0:
        message = stderr.decode("utf-8", errors="replace").strip()
        if not message:
            message = f"curl exit code {process.returncode}"
        raise RuntimeError(f"fetch_rss failed: {message}")
    return stdout.decode("utf-8", errors="replace")


async def read_rss_as_aids(url: str, sessdata: str | None = None) -> tuple[set[int], list[int]]:
    xml = await fetch_rss_xml(url=url, sessdata=sessdata)
    parsed = feedparser.parse(xml)
    if parsed.bozo:
        LOGGER.warning("RSS parser reported bozo=%s: %s", parsed.bozo, parsed.bozo_exception)

    ordered: list[int] = []
    seen: set[int] = set()
    for entry in parsed.entries:
        aid = None
        for candidate in _iter_entry_links(entry):
            aid = extract_aid_from_text(candidate)
            if aid is not None:
                break
        if aid is None:
            LOGGER.warning("Skip RSS item without BV/av link: %s", getattr(entry, "title", "<no-title>"))
            continue
        if aid not in seen:
            ordered.append(aid)
            seen.add(aid)
    return seen, ordered

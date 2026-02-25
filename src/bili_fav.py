from __future__ import annotations

import asyncio
import logging
from typing import Any

from bilibili_api import favorite_list, user
from bilibili_api.favorite_list import (
    FavoriteList,
    FavoriteListContentOrder,
    FavoriteListType,
    create_video_favorite_list,
    delete_video_favorite_list_content,
    get_video_favorite_list,
)
from bilibili_api.utils.aid_bvid_transformer import bvid2aid
from bilibili_api.utils.network import Credential
from bilibili_api.video import Video

LOGGER = logging.getLogger(__name__)


def _as_dict(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict):
        return payload
    raise ValueError(f"Expected dict payload, got {type(payload)}")


def _extract_list(payload: dict[str, Any], *keys: str) -> list[dict[str, Any]]:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    data = payload.get("data")
    if isinstance(data, dict):
        for key in keys:
            value = data.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def _extract_int(payload: dict[str, Any], *keys: str) -> int | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
    data = payload.get("data")
    if isinstance(data, dict):
        for key in keys:
            value = data.get(key)
            if isinstance(value, int):
                return value
            if isinstance(value, str) and value.isdigit():
                return int(value)
    return None



def _extract_total_count(payload: dict[str, Any]) -> int | None:
    info = payload.get("info")
    if isinstance(info, dict):
        value = info.get("media_count")
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)

    data = payload.get("data")
    if isinstance(data, dict):
        info = data.get("info")
        if isinstance(info, dict):
            value = info.get("media_count")
            if isinstance(value, int):
                return value
            if isinstance(value, str) and value.isdigit():
                return int(value)
    return None


def _extract_has_more(payload: dict[str, Any]) -> bool | None:
    for container in (payload, payload.get("data") if isinstance(payload.get("data"), dict) else None):
        if not isinstance(container, dict):
            continue
        value = container.get("has_more")
        if isinstance(value, bool):
            return value
        if isinstance(value, int):
            return value != 0
        if isinstance(value, str) and value.isdigit():
            return int(value) != 0
    return None

def _extract_media_aid(item: dict[str, Any]) -> int | None:
    for key in ("id", "aid"):
        value = item.get(key)
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)

    upper = item.get("upper")
    if isinstance(upper, dict):
        value = upper.get("aid")
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)

    bvid = item.get("bvid") or item.get("bv_id")
    if isinstance(bvid, str) and bvid.startswith("BV"):
        try:
            return int(bvid2aid(bvid))
        except Exception:
            return None
    return None


async def maybe_refresh_credential(credential: Credential) -> bool:
    if await credential.check_refresh():
        await credential.refresh()
        return True
    return False


async def check_credential_valid(credential: Credential) -> bool:
    return bool(await credential.check_valid())


async def get_self_mid(credential: Credential) -> int:
    info = _as_dict(await user.get_self_info(credential))
    mid = _extract_int(info, "mid")
    if mid is None:
        raise ValueError("Cannot parse current user mid from get_self_info result")
    return mid


async def ensure_favorite_list(
    mid: int,
    title: str,
    private: bool,
    credential: Credential,
) -> int:
    payload = _as_dict(await get_video_favorite_list(uid=mid, credential=credential))
    lists = _extract_list(payload, "list")
    for item in lists:
        if item.get("title") == title:
            media_id = _extract_int(item, "id", "media_id", "fid")
            if media_id is not None:
                return media_id

    LOGGER.info("Favorite list %r not found, creating it", title)
    created = _as_dict(
        await create_video_favorite_list(
            title=title,
            private=private,
            credential=credential,
        )
    )
    media_id = _extract_int(created, "id", "media_id", "fid")
    if media_id is None:
        raise ValueError(f"Cannot parse media_id from create response: {created}")
    return media_id


async def get_favorite_aids_ordered(
    media_id: int,
    credential: Credential,
    page_delay_seconds: float = 0.0,
) -> list[int]:
    fav = FavoriteList(
        type_=FavoriteListType.VIDEO,
        media_id=media_id,
        credential=credential,
    )
    ordered: list[int] = []
    seen: set[int] = set()
    page = 1

    while True:
        payload = _as_dict(
            await fav.get_content_video(page=page, order=FavoriteListContentOrder.MTIME)
        )
        medias = _extract_list(payload, "medias")
        if not medias:
            break

        for item in medias:
            aid = _extract_media_aid(item)
            if aid is None or aid in seen:
                continue
            ordered.append(aid)
            seen.add(aid)

        has_more = _extract_has_more(payload)
        if has_more is False:
            break

        total_count = _extract_total_count(payload)
        if total_count is not None and len(ordered) >= total_count:
            break

        if len(medias) < 20:
            break

        page += 1
        if page_delay_seconds > 0:
            await asyncio.sleep(page_delay_seconds)
    return ordered


async def remove_from_favorite(
    media_id: int,
    aids: list[int],
    credential: Credential,
) -> None:
    if not aids:
        return
    await delete_video_favorite_list_content(
        media_id=media_id,
        aids=aids,
        credential=credential,
    )


async def add_to_favorite(media_id: int, aid: int, credential: Credential) -> None:
    video = Video(aid=aid, credential=credential)
    await video.set_favorite(add_media_ids=[media_id])

from __future__ import annotations

import asyncio
import logging
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

from src.bili_fav import (
    add_to_favorite,
    check_credential_valid,
    ensure_favorite_list,
    get_favorite_aids_ordered,
    get_self_mid,
    maybe_refresh_credential,
    remove_from_favorite,
)
from src.config import AppConfig
from src.credential_store import load_credential, load_state, save_credential, save_state
from src.notify import EmailNotifier
from src.rss_reader import read_rss_as_aids

LOGGER = logging.getLogger(__name__)


def _chunked(values: Iterable[int], size: int) -> list[list[int]]:
    chunk: list[int] = []
    chunks: list[list[int]] = []
    for value in values:
        chunk.append(value)
        if len(chunk) >= size:
            chunks.append(chunk)
            chunk = []
    if chunk:
        chunks.append(chunk)
    return chunks


@dataclass(frozen=True)
class SyncResult:
    media_id: int
    desired_count: int
    existing_count: int
    removed_count: int
    added_count: int
    refreshed_cookie: bool


class SyncService:
    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._notifier = EmailNotifier(config.smtp)

    async def _notify_failure(self, step: str, error: Exception) -> None:
        content = [
            f"时间: {datetime.now(timezone.utc).isoformat()}",
            f"步骤: {step}",
            f"错误: {type(error).__name__}: {error}",
            "",
            "请重新登录 B 站并更新 credential.json（尤其确保 ac_time_value 存在）。",
            "",
            "回溯:",
            traceback.format_exc(),
        ]
        body = "\n".join(content)
        try:
            await self._notifier.send("biliRSS2Fav 同步失败告警", body)
        except Exception as mail_error:
            LOGGER.error("Send alert email failed: %s", mail_error)

    @staticmethod
    def _compute_capacity_evictions(
        existing_ordered: list[int],
        to_remove: set[int],
        to_add: set[int],
        max_items: int,
    ) -> set[int]:
        after = len(existing_ordered) - len(to_remove) + len(to_add)
        if after <= max_items:
            return set()

        extra = after - max_items
        removable_oldest = [aid for aid in reversed(existing_ordered) if aid not in to_remove]
        evict = set(removable_oldest[:extra])
        return evict

    async def sync_once(self) -> SyncResult:
        step = "load_credential"
        try:
            credential = load_credential(self._config.credential_json)
            state = load_state(self._config.state_json)

            step = "check_credential_valid"
            if not await check_credential_valid(credential):
                raise RuntimeError("Credential is invalid (check_valid=False)")

            step = "refresh_credential"
            refreshed = await maybe_refresh_credential(credential)
            if refreshed:
                save_credential(self._config.credential_json, credential)
                LOGGER.info("Credential refreshed and persisted")

            step = "ensure_favorite_list"
            mid = await get_self_mid(credential)
            media_id = await ensure_favorite_list(
                mid=mid,
                title=self._config.fav_title,
                private=self._config.fav_private,
                credential=credential,
            )

            step = "read_rss"
            desired_set, desired_ordered = await read_rss_as_aids(
                url=self._config.rss_url,
                sessdata=credential.sessdata,
            )

            step = "read_favorite_content"
            existing_ordered = await get_favorite_aids_ordered(media_id=media_id, credential=credential)
            existing_set = set(existing_ordered)

            to_add = desired_set - existing_set
            # 保留收藏夹中 RSS 已不存在的视频；仅在容量控制场景下删除。
            to_remove: set[int] = set()
            to_remove |= self._compute_capacity_evictions(
                existing_ordered=existing_ordered,
                to_remove=to_remove,
                to_add=to_add,
                max_items=self._config.fav_max_items,
            )

            removed_count = 0
            added_count = 0

            step = "apply_remove"
            for chunk in _chunked(sorted(to_remove), 50):
                await remove_from_favorite(media_id=media_id, aids=chunk, credential=credential)
                removed_count += len(chunk)
                await asyncio.sleep(self._config.op_delay_seconds)

            step = "apply_add"
            for aid in desired_ordered:
                if aid not in to_add:
                    continue
                await add_to_favorite(media_id=media_id, aid=aid, credential=credential)
                added_count += 1
                await asyncio.sleep(self._config.op_delay_seconds)

            state["media_id"] = media_id
            state["last_sync_ts"] = int(datetime.now(timezone.utc).timestamp())
            step = "save_state"
            save_state(self._config.state_json, state)

            return SyncResult(
                media_id=media_id,
                desired_count=len(desired_set),
                existing_count=len(existing_set),
                removed_count=removed_count,
                added_count=added_count,
                refreshed_cookie=refreshed,
            )
        except Exception as error:
            await self._notify_failure(step=step, error=error)
            raise

    async def run_daemon(self) -> None:
        while True:
            try:
                result = await self.sync_once()
                LOGGER.info(
                    "Sync done media_id=%s desired=%s existing=%s removed=%s added=%s refreshed_cookie=%s",
                    result.media_id,
                    result.desired_count,
                    result.existing_count,
                    result.removed_count,
                    result.added_count,
                    result.refreshed_cookie,
                )
            except Exception as error:
                LOGGER.error("Sync failed: %s", error)
            await asyncio.sleep(self._config.sync_interval_seconds)

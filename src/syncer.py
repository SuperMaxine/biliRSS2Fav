from __future__ import annotations

import asyncio
import logging
import random
import time
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Awaitable, Callable, Iterable, TypeVar

from bilibili_api.exceptions.NetworkException import NetworkException

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
T = TypeVar("T")


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
        self._last_alert_at: dict[str, float] = {}

    @staticmethod
    def _is_risk_control_412(error: Exception) -> bool:
        return isinstance(error, NetworkException) and error.status == 412

    @staticmethod
    def _build_alert_key(step: str, error: Exception) -> str:
        if isinstance(error, NetworkException):
            return f"{step}:NetworkException:{error.status}"
        return f"{step}:{type(error).__name__}:{str(error)[:160]}"

    @staticmethod
    def _format_error_summary(error: Exception) -> str:
        if isinstance(error, NetworkException):
            if error.status == 412:
                return "NetworkException(status=412, risk_control)"
            return f"NetworkException(status={error.status})"
        message = str(error).strip().replace("\n", " ")
        if len(message) > 300:
            message = message[:300] + "..."
        return f"{type(error).__name__}: {message}"

    def _should_send_alert(self, step: str, error: Exception) -> bool:
        cooldown = max(0, self._config.alert_cooldown_seconds)
        if cooldown == 0:
            return True

        key = self._build_alert_key(step=step, error=error)
        now = time.monotonic()
        last_sent = self._last_alert_at.get(key)
        if last_sent is not None and now - last_sent < cooldown:
            remain = int(cooldown - (now - last_sent))
            LOGGER.warning("Suppress duplicate alert within cooldown: key=%s remain=%ss", key, remain)
            return False
        self._last_alert_at[key] = now
        return True

    def _build_failure_advice(self, error: Exception) -> list[str]:
        if self._is_risk_control_412(error):
            return [
                "判断：该错误属于 B 站风控（HTTP 412），通常由请求频率/IP 指纹触发，不等同于登录失效。",
                "建议：先暂停 10-30 分钟后重试，并提高 OP_DELAY_SECONDS/SYNC_INTERVAL_SECONDS。",
                "建议：避免多实例共用同一账号或同一出口 IP 并发请求。",
                "建议：若持续出现，可尝试使用 curl_cffi 客户端并启用浏览器指纹模拟。",
            ]
        if isinstance(error, TimeoutError):
            return [
                "判断：本轮同步执行超时，通常是网络抖动或接口长时间无响应。",
                "建议：检查网络连通性并稍后重试，可适当调大 SYNC_ONCE_TIMEOUT_SECONDS。",
            ]
        return [
            "请重新登录 B 站并更新 credential.json（尤其确保 ac_time_value 存在）。",
        ]

    async def _call_with_412_retry(self, step: str, call: Callable[[], Awaitable[T]]) -> T:
        attempts = max(1, self._config.risk_control_retry_times)
        base_delay = max(1.0, self._config.risk_control_retry_base_seconds)
        max_delay = max(base_delay, self._config.risk_control_retry_max_seconds)
        delay = base_delay

        for attempt in range(1, attempts + 1):
            try:
                return await self._await_with_step_timeout(step=step, awaitable=call())
            except NetworkException as error:
                if not self._is_risk_control_412(error) or attempt >= attempts:
                    raise
                sleep_seconds = min(delay, max_delay)
                jitter = random.uniform(0.0, min(3.0, sleep_seconds * 0.2))
                wait_seconds = sleep_seconds + jitter
                LOGGER.warning(
                    "Risk-control 412 at step=%s attempt=%s/%s, sleep %.2fs before retry",
                    step,
                    attempt,
                    attempts,
                    wait_seconds,
                )
                await asyncio.sleep(wait_seconds)
                delay = min(delay * 2, max_delay)

    async def _await_with_step_timeout(self, step: str, awaitable: Awaitable[T]) -> T:
        timeout = max(1, self._config.api_step_timeout_seconds)
        try:
            return await asyncio.wait_for(awaitable, timeout=timeout)
        except asyncio.TimeoutError as exc:
            raise TimeoutError(f"{step} timeout after {timeout}s") from exc

    async def _notify_failure(self, step: str, error: Exception) -> None:
        if not self._should_send_alert(step=step, error=error):
            return

        content = [
            f"时间: {datetime.now(timezone.utc).isoformat()}",
            f"步骤: {step}",
            f"错误: {self._format_error_summary(error)}",
            "",
            *self._build_failure_advice(error),
            "",
            "回溯:",
            traceback.format_exc(),
        ]
        body = "\n".join(content)
        try:
            self._notifier.send_with_timeout(
                "biliRSS2Fav 同步失败告警",
                body,
                timeout_seconds=max(1, self._config.alert_send_timeout_seconds),
            )
        except TimeoutError:
            LOGGER.error(
                "Send alert email timed out after %ss",
                self._config.alert_send_timeout_seconds,
            )
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
            LOGGER.info("Sync step: %s", step)
            credential = load_credential(self._config.credential_json)
            state = load_state(self._config.state_json)

            step = "check_credential_valid"
            if self._config.check_valid_enabled:
                LOGGER.info("Sync step: %s", step)
                valid = await asyncio.wait_for(
                    check_credential_valid(credential),
                    timeout=max(1, self._config.check_valid_timeout_seconds),
                )
                if not valid:
                    raise RuntimeError("Credential is invalid (check_valid=False)")
            else:
                LOGGER.info("Sync step: %s (skipped)", step)

            step = "refresh_credential"
            LOGGER.info("Sync step: %s", step)
            refreshed = False
            if self._config.credential_refresh_enabled:
                try:
                    refreshed = await asyncio.wait_for(
                        maybe_refresh_credential(credential),
                        timeout=max(1, self._config.credential_refresh_timeout_seconds),
                    )
                except asyncio.TimeoutError:
                    LOGGER.warning(
                        "Skip credential refresh due timeout (%ss)",
                        self._config.credential_refresh_timeout_seconds,
                    )
                if refreshed:
                    save_credential(self._config.credential_json, credential)
                    LOGGER.info("Credential refreshed and persisted")
            else:
                LOGGER.info("Sync step: %s (skipped)", step)

            step = "ensure_favorite_list"
            LOGGER.info("Sync step: %s", step)
            media_id = 0
            cached_media_id = state.get("media_id")
            if isinstance(cached_media_id, int) and cached_media_id > 0:
                media_id = cached_media_id
            elif isinstance(cached_media_id, str) and cached_media_id.isdigit():
                media_id = int(cached_media_id)

            if self._config.use_cached_media_id_first and media_id > 0:
                LOGGER.info("Use cached media_id from state: %s", media_id)
            else:
                mid = await self._await_with_step_timeout(
                    step="get_self_mid",
                    awaitable=get_self_mid(credential),
                )
                media_id = await self._await_with_step_timeout(
                    step=step,
                    awaitable=ensure_favorite_list(
                        mid=mid,
                        title=self._config.fav_title,
                        private=self._config.fav_private,
                        credential=credential,
                    ),
                )

            step = "read_rss"
            LOGGER.info("Sync step: %s", step)
            desired_set, desired_ordered = await self._await_with_step_timeout(
                step=step,
                awaitable=read_rss_as_aids(
                    url=self._config.rss_url,
                    sessdata=credential.sessdata,
                ),
            )

            step = "read_favorite_content"
            LOGGER.info("Sync step: %s", step)
            existing_ordered = await self._call_with_412_retry(
                step=step,
                call=lambda: get_favorite_aids_ordered(
                    media_id=media_id,
                    credential=credential,
                    page_delay_seconds=self._config.read_page_delay_seconds,
                ),
            )
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
            LOGGER.info("Sync step: %s", step)
            for chunk in _chunked(sorted(to_remove), 50):
                await self._await_with_step_timeout(
                    step=step,
                    awaitable=remove_from_favorite(
                        media_id=media_id,
                        aids=chunk,
                        credential=credential,
                    ),
                )
                removed_count += len(chunk)
                await asyncio.sleep(self._config.op_delay_seconds)

            step = "apply_add"
            LOGGER.info("Sync step: %s", step)
            for aid in desired_ordered:
                if aid not in to_add:
                    continue
                await self._await_with_step_timeout(
                    step=step,
                    awaitable=add_to_favorite(
                        media_id=media_id,
                        aid=aid,
                        credential=credential,
                    ),
                )
                added_count += 1
                await asyncio.sleep(self._config.op_delay_seconds)

            state["media_id"] = media_id
            state["last_sync_ts"] = int(datetime.now(timezone.utc).timestamp())
            step = "save_state"
            LOGGER.info("Sync step: %s", step)
            save_state(self._config.state_json, state)

            return SyncResult(
                media_id=media_id,
                desired_count=len(desired_set),
                existing_count=len(existing_set),
                removed_count=removed_count,
                added_count=added_count,
                refreshed_cookie=refreshed,
            )
        except asyncio.CancelledError:
            raise
        except Exception as error:
            await self._notify_failure(step=step, error=error)
            raise

    async def run_daemon(self) -> None:
        while True:
            sleep_seconds = self._config.sync_interval_seconds
            try:
                result = await asyncio.wait_for(
                    self.sync_once(), timeout=self._config.sync_once_timeout_seconds
                )
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
                if isinstance(error, asyncio.TimeoutError):
                    timeout_error = TimeoutError(
                        f"sync_once timeout after {self._config.sync_once_timeout_seconds}s"
                    )
                    await self._notify_failure(step="sync_once_timeout", error=timeout_error)
                    LOGGER.error("%s", timeout_error)
                else:
                    LOGGER.error("Sync failed: %s", self._format_error_summary(error))
                if self._is_risk_control_412(error):
                    sleep_seconds = max(
                        sleep_seconds,
                        int(self._config.risk_control_retry_max_seconds),
                    )
            await asyncio.sleep(sleep_seconds)

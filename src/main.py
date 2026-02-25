from __future__ import annotations

import argparse
import asyncio
import logging
from logging.handlers import RotatingFileHandler

from src.config import AppConfig
from src.syncer import SyncService


def _setup_bilibili_request_settings(config: AppConfig) -> None:
    try:
        from bilibili_api import request_settings
    except Exception as error:
        logging.getLogger(__name__).warning(
            "Skip bilibili_api request settings setup: %s", error
        )
        return

    request_settings.set("timeout", max(1.0, config.bili_request_timeout_seconds))
    request_settings.set("trust_env", config.bili_trust_env)
    logging.getLogger(__name__).info(
        "bilibili_api request settings: timeout=%ss trust_env=%s",
        config.bili_request_timeout_seconds,
        config.bili_trust_env,
    )


def _setup_logging(config: AppConfig, verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    config.log_file.parent.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(
        filename=config.log_file,
        maxBytes=max(config.log_max_bytes, 1),
        backupCount=max(config.log_backup_count, 1),
        encoding="utf-8",
    )
    stream_handler = logging.StreamHandler()
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        handlers=[stream_handler, file_handler],
        force=True,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="RSS -> Bilibili favorite syncer")
    parser.add_argument(
        "mode",
        nargs="?",
        default="once",
        choices=["once", "daemon"],
        help="run mode",
    )
    parser.add_argument("--env-file", default=".env", help="dotenv file path")
    parser.add_argument("--verbose", action="store_true", help="enable debug logs")
    return parser.parse_args()


async def _run(mode: str, config: AppConfig) -> None:
    service = SyncService(config)
    if mode == "once":
        result = await asyncio.wait_for(
            service.sync_once(), timeout=config.sync_once_timeout_seconds
        )
        logging.getLogger(__name__).info(
            "Sync done media_id=%s desired=%s existing=%s removed=%s added=%s refreshed_cookie=%s",
            result.media_id,
            result.desired_count,
            result.existing_count,
            result.removed_count,
            result.added_count,
            result.refreshed_cookie,
        )
        return
    await service.run_daemon()


def main() -> None:
    args = parse_args()
    config = AppConfig.load(dotenv_path=args.env_file)
    _setup_logging(config=config, verbose=args.verbose)
    _setup_bilibili_request_settings(config=config)
    logging.getLogger(__name__).info(
        "Log file enabled: %s (max_bytes=%s backup_count=%s)",
        config.log_file,
        config.log_max_bytes,
        config.log_backup_count,
    )
    try:
        asyncio.run(_run(mode=args.mode, config=config))
    except asyncio.TimeoutError:
        logging.getLogger(__name__).exception(
            "Fatal: sync_once timeout after %ss", config.sync_once_timeout_seconds
        )
        raise SystemExit(1)
    except Exception:
        logging.getLogger(__name__).exception("Fatal: unhandled exception")
        raise SystemExit(1)


if __name__ == "__main__":
    main()

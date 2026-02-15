from __future__ import annotations

import argparse
import asyncio
import logging

from src.config import AppConfig
from src.syncer import SyncService


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
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


async def _run(mode: str, env_file: str) -> None:
    config = AppConfig.load(dotenv_path=env_file)
    service = SyncService(config)
    if mode == "once":
        result = await service.sync_once()
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
    _setup_logging(verbose=args.verbose)
    asyncio.run(_run(mode=args.mode, env_file=args.env_file))


if __name__ == "__main__":
    main()

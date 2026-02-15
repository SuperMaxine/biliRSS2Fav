from __future__ import annotations

import argparse
import asyncio
import logging
import os
import time
from pathlib import Path

from dotenv import load_dotenv
from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from src.credential_store import save_json

LOGGER = logging.getLogger(__name__)

REQUIRED_FIELDS = (
    "SESSDATA",
    "bili_jct",
    "buvid3",
    "buvid4",
    "DedeUserID",
    "ac_time_value",
)
BASE_LOGIN_FIELDS = ("SESSDATA", "bili_jct", "DedeUserID")


def _mask_value(value: str) -> str:
    if len(value) <= 8:
        return "***"
    return f"{value[:4]}...{value[-4:]}"


def _pick_cookie_fields(cookies: list[dict]) -> dict[str, str]:
    extracted: dict[str, str] = {}
    for cookie in cookies:
        name = cookie.get("name")
        value = cookie.get("value")
        if not isinstance(name, str) or not isinstance(value, str):
            continue
        if name not in REQUIRED_FIELDS:
            continue
        if not value:
            continue
        if name not in extracted or len(value) > len(extracted[name]):
            extracted[name] = value
    return extracted


async def _read_local_storage_token(page: Page) -> str:
    script = """
() => {
  const keys = ['ac_time_value', 'refresh_token', 'AC_TIME_VALUE'];
  for (const key of keys) {
    const value = window.localStorage.getItem(key);
    if (value) return value;
  }
  return '';
}
"""
    try:
        value = await page.evaluate(script)
    except Exception:
        return ""
    return value if isinstance(value, str) else ""


async def _collect_fields(context: BrowserContext, page: Page) -> dict[str, str]:
    cookies = await context.cookies(
        ["https://www.bilibili.com", "https://passport.bilibili.com", "https://api.bilibili.com"]
    )
    extracted = _pick_cookie_fields(cookies)

    if not extracted.get("ac_time_value"):
        token = await _read_local_storage_token(page)
        if token:
            extracted["ac_time_value"] = token
    return extracted


async def _wait_until_logged_in(
    context: BrowserContext,
    page: Page,
    timeout_seconds: int,
    poll_seconds: float,
) -> dict[str, str]:
    deadline = time.monotonic() + timeout_seconds
    last_fields: dict[str, str] = {}
    while time.monotonic() < deadline:
        fields = await _collect_fields(context, page)
        last_fields = fields
        if all(fields.get(k) for k in BASE_LOGIN_FIELDS):
            return fields
        await asyncio.sleep(poll_seconds)
    raise TimeoutError(
        "Login timeout. Missing base fields: "
        + ", ".join([k for k in BASE_LOGIN_FIELDS if not last_fields.get(k)])
    )


async def _wait_until_all_fields(
    context: BrowserContext,
    page: Page,
    timeout_seconds: int = 30,
    poll_seconds: float = 2.0,
) -> dict[str, str]:
    deadline = time.monotonic() + timeout_seconds
    last_fields: dict[str, str] = {}
    while time.monotonic() < deadline:
        fields = await _collect_fields(context, page)
        last_fields = fields
        if all(fields.get(k) for k in REQUIRED_FIELDS):
            return fields
        await asyncio.sleep(poll_seconds)
    return last_fields


async def run_login_capture(
    output_path: Path,
    timeout_seconds: int,
    poll_seconds: float,
    headless: bool,
    keep_open: bool,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        browser: Browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context()
        page = await context.new_page()

        try:
            await page.goto("https://passport.bilibili.com/login", wait_until="domcontentloaded")
            print("浏览器已打开，请扫码登录或手动输入账号登录。")
            print("登录成功后脚本会自动提取 Cookie 并写入 credential.json。")

            _ = await _wait_until_logged_in(
                context=context,
                page=page,
                timeout_seconds=timeout_seconds,
                poll_seconds=poll_seconds,
            )

            await page.goto("https://www.bilibili.com", wait_until="domcontentloaded")
            try:
                await context.request.get("https://api.bilibili.com/x/web-interface/nav")
            except Exception:
                LOGGER.warning("Failed to call nav api for cookie warm-up", exc_info=True)

            fields = await _wait_until_all_fields(context=context, page=page)
            missing = [k for k in REQUIRED_FIELDS if not fields.get(k)]
            if missing:
                raise RuntimeError(
                    "Login detected but some required fields are still missing: "
                    + ", ".join(missing)
                    + ". Please retry login and ensure account page fully loads."
                )

            save_json(output_path, {key: fields[key] for key in REQUIRED_FIELDS})
            print(f"凭据已写入: {output_path}")
            for key in REQUIRED_FIELDS:
                print(f"{key}={_mask_value(fields[key])}")
        finally:
            if keep_open:
                print("已启用 --keep-open，浏览器将保持打开。按 Ctrl+C 结束。")
                while True:
                    await asyncio.sleep(3600)
            await context.close()
            await browser.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Open a controlled browser and capture Bilibili credential cookies."
    )
    parser.add_argument("--env-file", default=".env", help="dotenv file path")
    parser.add_argument(
        "--credential-json",
        default="",
        help="output file path, defaults to CREDENTIAL_JSON from env",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=300,
        help="max wait time for login completion",
    )
    parser.add_argument(
        "--poll-seconds",
        type=float,
        default=2.0,
        help="poll interval while waiting login cookies",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="run browser headless (not recommended for QR login)",
    )
    parser.add_argument(
        "--keep-open",
        action="store_true",
        help="keep browser open after capture",
    )
    parser.add_argument("--verbose", action="store_true", help="enable debug logs")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    load_dotenv(dotenv_path=args.env_file, override=False)
    output = args.credential_json.strip() or os.getenv("CREDENTIAL_JSON", "data/credential.json")
    asyncio.run(
        run_login_capture(
            output_path=Path(output),
            timeout_seconds=args.timeout_seconds,
            poll_seconds=args.poll_seconds,
            headless=args.headless,
            keep_open=args.keep_open,
        )
    )


if __name__ == "__main__":
    main()

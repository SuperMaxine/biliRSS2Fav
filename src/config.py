from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


def _parse_bool(value: str, key: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"Invalid boolean for {key}: {value!r}")


def _parse_int(value: str, key: str) -> int:
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"Invalid integer for {key}: {value!r}") from exc


@dataclass(frozen=True)
class SMTPConfig:
    host: str
    port: int
    user: str
    password: str
    to_email: str
    from_name: str

    @property
    def enabled(self) -> bool:
        return all([self.host, self.port, self.user, self.password, self.to_email])


@dataclass(frozen=True)
class AppConfig:
    rss_url: str
    fav_title: str
    fav_private: bool
    fav_max_items: int
    sync_interval_seconds: int
    op_delay_seconds: float
    credential_json: Path
    state_json: Path
    smtp: SMTPConfig

    @staticmethod
    def load(dotenv_path: str | None = ".env") -> "AppConfig":
        if dotenv_path:
            # CLI 已显式传入 env 文件时，应以该文件为准，避免被进程环境中的旧值覆盖。
            load_dotenv(dotenv_path=dotenv_path, override=True)

        rss_url = os.getenv("RSS_URL", "").strip()
        fav_title = os.getenv("FAV_TITLE", "").strip()
        missing = []
        if not rss_url:
            missing.append("RSS_URL")
        if not fav_title:
            missing.append("FAV_TITLE")
        if missing:
            raise ValueError(f"Missing required env vars: {', '.join(missing)}")

        fav_private = _parse_bool(os.getenv("FAV_PRIVATE", "false"), "FAV_PRIVATE")
        fav_max_items = _parse_int(os.getenv("FAV_MAX_ITEMS", "200"), "FAV_MAX_ITEMS")
        sync_interval_seconds = _parse_int(
            os.getenv("SYNC_INTERVAL_SECONDS", "300"), "SYNC_INTERVAL_SECONDS"
        )
        op_delay_seconds = float(os.getenv("OP_DELAY_SECONDS", "0.3"))

        credential_json = Path(os.getenv("CREDENTIAL_JSON", "data/credential.json"))
        state_json = Path(os.getenv("STATE_JSON", "data/state.json"))

        smtp_port_raw = os.getenv("SMTP_PORT", "").strip()
        smtp_port = int(smtp_port_raw) if smtp_port_raw else 0
        smtp = SMTPConfig(
            host=os.getenv("SMTP_HOST", "").strip(),
            port=smtp_port,
            user=os.getenv("SMTP_USER", "").strip(),
            password=os.getenv("SMTP_PASS", "").strip(),
            to_email=os.getenv("ALERT_TO_EMAIL", "").strip(),
            from_name=os.getenv("SMTP_FROM_NAME", "biliRSS2Fav").strip(),
        )
        return AppConfig(
            rss_url=rss_url,
            fav_title=fav_title,
            fav_private=fav_private,
            fav_max_items=fav_max_items,
            sync_interval_seconds=sync_interval_seconds,
            op_delay_seconds=op_delay_seconds,
            credential_json=credential_json,
            state_json=state_json,
            smtp=smtp,
        )

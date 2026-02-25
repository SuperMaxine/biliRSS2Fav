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


def _parse_float(value: str, key: str) -> float:
    try:
        return float(value)
    except ValueError as exc:
        raise ValueError(f"Invalid float for {key}: {value!r}") from exc


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
    sync_once_timeout_seconds: int
    api_step_timeout_seconds: int
    check_valid_enabled: bool
    check_valid_timeout_seconds: int
    credential_refresh_enabled: bool
    credential_refresh_timeout_seconds: int
    use_cached_media_id_first: bool
    op_delay_seconds: float
    read_page_delay_seconds: float
    risk_control_retry_times: int
    risk_control_retry_base_seconds: float
    risk_control_retry_max_seconds: float
    alert_cooldown_seconds: int
    alert_send_timeout_seconds: int
    bili_request_timeout_seconds: float
    bili_trust_env: bool
    log_file: Path
    log_max_bytes: int
    log_backup_count: int
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
        sync_once_timeout_seconds = _parse_int(
            os.getenv("SYNC_ONCE_TIMEOUT_SECONDS", "420"), "SYNC_ONCE_TIMEOUT_SECONDS"
        )
        api_step_timeout_seconds = _parse_int(
            os.getenv("API_STEP_TIMEOUT_SECONDS", "45"), "API_STEP_TIMEOUT_SECONDS"
        )
        check_valid_enabled = _parse_bool(
            os.getenv("CHECK_VALID_ENABLED", "false"), "CHECK_VALID_ENABLED"
        )
        check_valid_timeout_seconds = _parse_int(
            os.getenv("CHECK_VALID_TIMEOUT_SECONDS", "20"), "CHECK_VALID_TIMEOUT_SECONDS"
        )
        credential_refresh_enabled = _parse_bool(
            os.getenv("CREDENTIAL_REFRESH_ENABLED", "true"), "CREDENTIAL_REFRESH_ENABLED"
        )
        credential_refresh_timeout_seconds = _parse_int(
            os.getenv("CREDENTIAL_REFRESH_TIMEOUT_SECONDS", "30"),
            "CREDENTIAL_REFRESH_TIMEOUT_SECONDS",
        )
        use_cached_media_id_first = _parse_bool(
            os.getenv("USE_CACHED_MEDIA_ID_FIRST", "true"), "USE_CACHED_MEDIA_ID_FIRST"
        )
        op_delay_seconds = _parse_float(os.getenv("OP_DELAY_SECONDS", "0.3"), "OP_DELAY_SECONDS")
        read_page_delay_seconds = _parse_float(
            os.getenv("READ_PAGE_DELAY_SECONDS", "0.5"), "READ_PAGE_DELAY_SECONDS"
        )
        risk_control_retry_times = _parse_int(
            os.getenv("RISK_CONTROL_RETRY_TIMES", "4"), "RISK_CONTROL_RETRY_TIMES"
        )
        risk_control_retry_base_seconds = _parse_float(
            os.getenv("RISK_CONTROL_RETRY_BASE_SECONDS", "5"),
            "RISK_CONTROL_RETRY_BASE_SECONDS",
        )
        risk_control_retry_max_seconds = _parse_float(
            os.getenv("RISK_CONTROL_RETRY_MAX_SECONDS", "120"),
            "RISK_CONTROL_RETRY_MAX_SECONDS",
        )
        alert_cooldown_seconds = _parse_int(
            os.getenv("ALERT_COOLDOWN_SECONDS", "1800"), "ALERT_COOLDOWN_SECONDS"
        )
        alert_send_timeout_seconds = _parse_int(
            os.getenv("ALERT_SEND_TIMEOUT_SECONDS", "10"), "ALERT_SEND_TIMEOUT_SECONDS"
        )
        bili_request_timeout_seconds = _parse_float(
            os.getenv("BILI_REQUEST_TIMEOUT_SECONDS", "20"), "BILI_REQUEST_TIMEOUT_SECONDS"
        )
        bili_trust_env = _parse_bool(os.getenv("BILI_TRUST_ENV", "false"), "BILI_TRUST_ENV")
        log_file = Path(os.getenv("LOG_FILE", "logs/biliRSS2Fav.log").strip())
        log_max_bytes = _parse_int(os.getenv("LOG_MAX_BYTES", "10485760"), "LOG_MAX_BYTES")
        log_backup_count = _parse_int(os.getenv("LOG_BACKUP_COUNT", "5"), "LOG_BACKUP_COUNT")

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
            sync_once_timeout_seconds=sync_once_timeout_seconds,
            api_step_timeout_seconds=api_step_timeout_seconds,
            check_valid_enabled=check_valid_enabled,
            check_valid_timeout_seconds=check_valid_timeout_seconds,
            credential_refresh_enabled=credential_refresh_enabled,
            credential_refresh_timeout_seconds=credential_refresh_timeout_seconds,
            use_cached_media_id_first=use_cached_media_id_first,
            op_delay_seconds=op_delay_seconds,
            read_page_delay_seconds=read_page_delay_seconds,
            risk_control_retry_times=risk_control_retry_times,
            risk_control_retry_base_seconds=risk_control_retry_base_seconds,
            risk_control_retry_max_seconds=risk_control_retry_max_seconds,
            alert_cooldown_seconds=alert_cooldown_seconds,
            alert_send_timeout_seconds=alert_send_timeout_seconds,
            bili_request_timeout_seconds=bili_request_timeout_seconds,
            bili_trust_env=bili_trust_env,
            log_file=log_file,
            log_max_bytes=log_max_bytes,
            log_backup_count=log_backup_count,
            credential_json=credential_json,
            state_json=state_json,
            smtp=smtp,
        )

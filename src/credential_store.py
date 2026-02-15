from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from bilibili_api.utils.network import Credential


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    tmp_path.replace(path)


def load_json(path: Path, default: dict[str, Any] | None = None) -> dict[str, Any]:
    if not path.exists():
        if default is not None:
            return default.copy()
        raise FileNotFoundError(f"Missing file: {path}")
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return {} if default is None else default.copy()
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def save_json(path: Path, data: dict[str, Any]) -> None:
    _atomic_write_json(path, data)


def load_credential(path: Path) -> Credential:
    cookies = load_json(path)
    return Credential.from_cookies(cookies)


def save_credential(path: Path, credential: Credential) -> None:
    save_json(path, credential.get_cookies())


def load_state(path: Path) -> dict[str, Any]:
    return load_json(path, default={"media_id": 0, "last_sync_ts": 0})


def save_state(path: Path, state: dict[str, Any]) -> None:
    save_json(path, state)

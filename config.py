from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nonebot import get_driver


@dataclass(frozen=True, slots=True)
class BotScopeConfig:
    adapter_instance_id: str
    bot_app_id: str


@dataclass(frozen=True, slots=True)
class SendConfig:
    db_path: Path
    adapter_instance_id: str
    bot_app_id: str
    cross_context_user_id_stable: bool
    queue_size: int
    batch_size: int
    flush_interval_seconds: float
    resolver_timeout_seconds: float


def _get_setting(config: Any, name: str, default: Any) -> Any:
    return getattr(config, name, default)


def _read_gensokyo_app_id() -> str:
    root = Path(__file__).resolve().parents[3]
    config_path = root / "qqbot" / "config.yml"
    try:
        text = config_path.read_text(encoding="utf-8")
    except OSError:
        return ""
    match = re.search(r"^\s*app_id\s*:\s*['\"]?([0-9]+)", text, re.MULTILINE)
    return match.group(1) if match else ""


def load_send_config() -> SendConfig:
    config = get_driver().config
    plugin_dir = Path(__file__).resolve().parent
    configured_db_path = _get_setting(config, "amia_send_db_path", "")
    db_path = Path(configured_db_path) if configured_db_path else plugin_dir / "data.db"
    app_id = str(_get_setting(config, "amia_send_bot_app_id", "") or _read_gensokyo_app_id())
    return SendConfig(
        db_path=db_path,
        adapter_instance_id=str(
            _get_setting(config, "amia_send_adapter_instance_id", "qqbot-local")
        ),
        bot_app_id=app_id,
        cross_context_user_id_stable=bool(
            _get_setting(config, "amia_send_cross_context_user_id_stable", False)
        ),
        queue_size=max(100, int(_get_setting(config, "amia_send_writer_queue_size", 2000))),
        batch_size=max(1, int(_get_setting(config, "amia_send_writer_batch_size", 100))),
        flush_interval_seconds=max(
            0.05, float(_get_setting(config, "amia_send_writer_flush_seconds", 0.5))
        ),
        resolver_timeout_seconds=max(
            0.01, float(_get_setting(config, "amia_send_resolver_timeout_seconds", 0.2))
        ),
    )

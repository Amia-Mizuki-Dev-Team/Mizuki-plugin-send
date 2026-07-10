"""Scoped message activity statistics for the local Amia deployment."""

from __future__ import annotations

from nonebot import get_driver, on_message
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.plugin import PluginMetadata

from .commands import register_commands
from .service import activity_service

__plugin_meta__ = PluginMetadata(
    name="群聊活动统计",
    description="按 Gensokyo 实例与 AppID 作用域记录群聊活动和 DAU。",
    usage=(
        "今日发言 / 本月发言 / 今年发言：本群排行榜\n"
        "今日DAU / 本月DAU / 今年DAU：管理员活动概览"
    ),
    type="application",
    supported_adapters={"~onebot.v11"},
)

driver = get_driver()


@driver.on_startup
async def _start_activity_service() -> None:
    await activity_service.start()


@driver.on_shutdown
async def _stop_activity_service() -> None:
    await activity_service.stop()


recorder = on_message(priority=0, block=False)


@recorder.handle()
async def _record_message(event: MessageEvent) -> None:
    await activity_service.record_event(event)


register_commands(activity_service)

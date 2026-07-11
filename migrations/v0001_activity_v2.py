from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import aiosqlite

from ..storage import ActivityStore


async def dry_run(db_path: str | Path) -> dict[str, Any]:
    """Inspect an existing send database without schema or data mutation."""
    return await ActivityStore(Path(db_path)).legacy_dry_run()


async def migrate(
    db_path: str | Path,
    adapter_instance_id: str,
    bot_app_id: str,
    bot_id: str,
) -> None:
    db_path = Path(db_path)
    if not db_path.exists():
        return

    # First perform dry_run
    store = ActivityStore(db_path)
    res = await store.legacy_dry_run()
    if not res.get("ok"):
        raise RuntimeError(f"Migration dry_run failed: {res}")

    tables = res.get("tables", {})
    # If expected legacy tables do not exist, nothing to migrate
    if not any(t.get("exists") for t in tables.values()):
        return

    backup_path = db_path.with_name(
        f"{db_path.name}.pre-v2.{datetime.now().strftime('%Y%m%d%H%M%S')}.bak"
    )
    try:
        shutil.copy2(db_path, backup_path)
    except OSError as exc:
        raise RuntimeError(f"unable to create migration backup {backup_path}") from exc

    async with aiosqlite.connect(db_path) as db:
        await db.execute("PRAGMA busy_timeout=10000")
        await db.execute("BEGIN IMMEDIATE")
        try:
            # 1. Create the new schema tables
            await db.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version TEXT PRIMARY KEY,
                    checksum TEXT NOT NULL,
                    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    status TEXT NOT NULL,
                    details_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE TABLE IF NOT EXISTS activity_daily (
                    date TEXT NOT NULL,
                    adapter_type TEXT NOT NULL,
                    adapter_instance_id TEXT NOT NULL,
                    bot_id TEXT NOT NULL,
                    bot_app_id TEXT NOT NULL,
                    context_type TEXT NOT NULL CHECK(context_type IN ('group', 'private')),
                    context_id TEXT NOT NULL,
                    gensokyo_user_id TEXT NOT NULL,
                    canonical_user_id TEXT,
                    display_name TEXT,
                    message_count INTEGER NOT NULL DEFAULT 0 CHECK(message_count >= 0),
                    total_bytes INTEGER NOT NULL DEFAULT 0 CHECK(total_bytes >= 0),
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    legacy_source TEXT,
                    PRIMARY KEY (
                        date, adapter_type, adapter_instance_id, bot_id, bot_app_id,
                        context_type, context_id, gensokyo_user_id
                    )
                );
                CREATE TABLE IF NOT EXISTS activity_hourly (
                    date TEXT NOT NULL,
                    hour INTEGER NOT NULL CHECK(hour BETWEEN 0 AND 23),
                    adapter_type TEXT NOT NULL,
                    adapter_instance_id TEXT NOT NULL,
                    bot_id TEXT NOT NULL,
                    bot_app_id TEXT NOT NULL,
                    context_type TEXT NOT NULL CHECK(context_type IN ('group', 'private')),
                    context_id TEXT NOT NULL,
                    message_count INTEGER NOT NULL DEFAULT 0,
                    total_bytes INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (
                        date, hour, adapter_type, adapter_instance_id, bot_id,
                        bot_app_id, context_type, context_id
                    )
                );
                CREATE TABLE IF NOT EXISTS legacy_daily_metrics (
                    date TEXT NOT NULL,
                    adapter_type TEXT NOT NULL,
                    adapter_instance_id TEXT NOT NULL,
                    bot_id TEXT NOT NULL,
                    bot_app_id TEXT NOT NULL,
                    total_bytes INTEGER NOT NULL DEFAULT 0,
                    source_table TEXT NOT NULL,
                    PRIMARY KEY (
                        date, adapter_type, adapter_instance_id, bot_id,
                        bot_app_id, source_table
                    )
                );
                CREATE INDEX IF NOT EXISTS idx_activity_group_range ON activity_daily (
                    adapter_instance_id, bot_app_id, bot_id, context_type, context_id, date
                );
                CREATE INDEX IF NOT EXISTS idx_activity_instance_dau ON activity_daily (
                    adapter_instance_id, bot_app_id, date, gensokyo_user_id
                );
                CREATE INDEX IF NOT EXISTS idx_activity_canonical_dau ON activity_daily (
                    adapter_instance_id, bot_app_id, date, canonical_user_id
                ) WHERE canonical_user_id IS NOT NULL;
                CREATE INDEX IF NOT EXISTS idx_activity_user_range ON activity_daily (
                    adapter_instance_id, bot_app_id, gensokyo_user_id, date
                );
                CREATE INDEX IF NOT EXISTS idx_activity_hour_range ON activity_hourly (
                    adapter_instance_id, bot_app_id, context_type, context_id, date, hour
                );
                """
            )

            # 2. Rename old tables to backup tables
            if tables.get("msg_stats", {}).get("exists"):
                await db.execute("ALTER TABLE msg_stats RENAME TO msg_stats_legacy_bak")
            if tables.get("private_stats", {}).get("exists"):
                await db.execute("ALTER TABLE private_stats RENAME TO private_stats_legacy_bak")
            if tables.get("hourly_stats", {}).get("exists"):
                await db.execute("ALTER TABLE hourly_stats RENAME TO hourly_stats_legacy_bak")
            if tables.get("traffic_stats", {}).get("exists"):
                await db.execute("ALTER TABLE traffic_stats RENAME TO traffic_stats_legacy_bak")

            # 3. Copy data to the new tables
            if tables.get("msg_stats", {}).get("exists"):
                await db.execute(
                    """
                    INSERT INTO activity_daily (
                        date, adapter_type, adapter_instance_id, bot_id, bot_app_id,
                        context_type, context_id, gensokyo_user_id, canonical_user_id,
                        display_name, message_count, total_bytes, first_seen_at, last_seen_at, legacy_source
                    )
                    SELECT 
                        date, 'onebot.v11', ?, ?, ?,
                        'group', group_id, user_id, NULL,
                        NULL, count, 0, date || 'T00:00:00', date || 'T23:59:59', 'msg_stats'
                    FROM msg_stats_legacy_bak
                    """,
                    (adapter_instance_id, bot_id, bot_app_id),
                )

            if tables.get("private_stats", {}).get("exists"):
                await db.execute(
                    """
                    INSERT INTO activity_daily (
                        date, adapter_type, adapter_instance_id, bot_id, bot_app_id,
                        context_type, context_id, gensokyo_user_id, canonical_user_id,
                        display_name, message_count, total_bytes, first_seen_at, last_seen_at, legacy_source
                    )
                    SELECT 
                        date, 'onebot.v11', ?, ?, ?,
                        'private', user_id, user_id, NULL,
                        NULL, count, 0, date || 'T00:00:00', date || 'T23:59:59', 'private_stats'
                    FROM private_stats_legacy_bak
                    """,
                    (adapter_instance_id, bot_id, bot_app_id),
                )

            if tables.get("hourly_stats", {}).get("exists"):
                await db.execute(
                    """
                    INSERT INTO activity_hourly (
                        date, hour, adapter_type, adapter_instance_id, bot_id, bot_app_id,
                        context_type, context_id, message_count, total_bytes
                    )
                    SELECT 
                        date, hour, 'onebot.v11', ?, ?, ?,
                        'group', '*', count, 0
                    FROM hourly_stats_legacy_bak
                    """,
                    (adapter_instance_id, bot_id, bot_app_id),
                )

            if tables.get("traffic_stats", {}).get("exists"):
                await db.execute(
                    """
                    INSERT INTO legacy_daily_metrics (
                        date, adapter_type, adapter_instance_id, bot_id, bot_app_id,
                        total_bytes, source_table
                    )
                    SELECT 
                        date, 'onebot.v11', ?, ?, ?,
                        total_bytes, 'traffic_stats'
                    FROM traffic_stats_legacy_bak
                    """,
                    (adapter_instance_id, bot_id, bot_app_id),
                )

            # Verify message totals before recording the migration as applied.
            for source in ("msg_stats", "private_stats"):
                if not tables.get(source, {}).get("exists"):
                    continue
                async with db.execute(f"SELECT COALESCE(SUM(count), 0) FROM {source}_legacy_bak") as cursor:
                    source_total = (await cursor.fetchone())[0]
                async with db.execute("SELECT COALESCE(SUM(message_count), 0) FROM activity_daily WHERE legacy_source=?", (source,)) as cursor:
                    target_total = (await cursor.fetchone())[0]
                if source_total != target_total:
                    raise RuntimeError(f"migration validation failed for {source}: {source_total} != {target_total}")

            # 4. Record migration status
            await db.execute(
                """
                INSERT OR REPLACE INTO schema_migrations(version, checksum, status, details_json)
                VALUES (?, ?, 'applied', ?)
                """,
                (
                    "send-activity-v2-0001",
                    "migrated-from-legacy",
                    json.dumps({
                        "mode": "migrated",
                        "adapter_instance_id": adapter_instance_id,
                        "bot_app_id": bot_app_id,
                        "bot_id": bot_id,
                        "migrated_at": datetime.now().isoformat()
                    })
                )
            )
            await db.commit()
        except Exception:
            await db.rollback()
            raise

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional


class Database:
    def __init__(self, path: str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.lock = asyncio.Lock()

    async def setup(self) -> None:
        async with self.lock:
            self.conn.executescript(
                """
                PRAGMA journal_mode=WAL;

                CREATE TABLE IF NOT EXISTS linked_accounts (
                    discord_user_id TEXT PRIMARY KEY,
                    discord_username TEXT NOT NULL,
                    guild_id TEXT NOT NULL,
                    twitch_user_id TEXT NOT NULL UNIQUE,
                    twitch_login TEXT NOT NULL,
                    twitch_display_name TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS progress (
                    discord_user_id TEXT PRIMARY KEY,
                    total_points INTEGER NOT NULL DEFAULT 0,
                    watch_points INTEGER NOT NULL DEFAULT 0,
                    message_points INTEGER NOT NULL DEFAULT 0,
                    level INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS twitch_identities (
                    purpose TEXT PRIMARY KEY,
                    twitch_user_id TEXT NOT NULL,
                    twitch_login TEXT NOT NULL,
                    twitch_display_name TEXT NOT NULL,
                    access_token TEXT NOT NULL,
                    refresh_token TEXT,
                    expires_at INTEGER NOT NULL,
                    scopes_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS processed_webhook_messages (
                    message_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL
                );
                """
            )
            self.conn.commit()

    async def close(self) -> None:
        async with self.lock:
            self.conn.close()

    async def upsert_link(
        self,
        *,
        discord_user_id: int,
        discord_username: str,
        guild_id: int,
        twitch_user_id: str,
        twitch_login: str,
        twitch_display_name: str,
        now_iso: str,
    ) -> None:
        async with self.lock:
            existing_for_twitch = self.conn.execute(
                "SELECT discord_user_id FROM linked_accounts WHERE twitch_user_id = ?",
                (twitch_user_id,),
            ).fetchone()
            if existing_for_twitch and existing_for_twitch["discord_user_id"] != str(discord_user_id):
                raise ValueError("This Twitch account is already linked to another Discord user")

            self.conn.execute(
                """
                INSERT INTO linked_accounts (
                    discord_user_id,
                    discord_username,
                    guild_id,
                    twitch_user_id,
                    twitch_login,
                    twitch_display_name,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(discord_user_id) DO UPDATE SET
                    discord_username = excluded.discord_username,
                    guild_id = excluded.guild_id,
                    twitch_user_id = excluded.twitch_user_id,
                    twitch_login = excluded.twitch_login,
                    twitch_display_name = excluded.twitch_display_name,
                    updated_at = excluded.updated_at
                """,
                (
                    str(discord_user_id),
                    discord_username,
                    str(guild_id),
                    twitch_user_id,
                    twitch_login,
                    twitch_display_name,
                    now_iso,
                    now_iso,
                ),
            )
            self.conn.execute(
                """
                INSERT INTO progress (discord_user_id, total_points, watch_points, message_points, level, updated_at)
                VALUES (?, 0, 0, 0, 0, ?)
                ON CONFLICT(discord_user_id) DO NOTHING
                """,
                (str(discord_user_id), now_iso),
            )
            self.conn.commit()

    async def get_link_by_discord_user_id(self, discord_user_id: int) -> Optional[Dict[str, Any]]:
        async with self.lock:
            row = self.conn.execute(
                "SELECT * FROM linked_accounts WHERE discord_user_id = ?",
                (str(discord_user_id),),
            ).fetchone()
            return dict(row) if row else None

    async def list_links(self) -> List[Dict[str, Any]]:
        async with self.lock:
            rows = self.conn.execute("SELECT * FROM linked_accounts ORDER BY discord_user_id ASC").fetchall()
            return [dict(row) for row in rows]

    async def save_twitch_identity(
        self,
        *,
        purpose: str,
        twitch_user_id: str,
        twitch_login: str,
        twitch_display_name: str,
        access_token: str,
        refresh_token: str | None,
        expires_at: int,
        scopes: List[str],
        now_iso: str,
    ) -> None:
        async with self.lock:
            self.conn.execute(
                """
                INSERT INTO twitch_identities (
                    purpose,
                    twitch_user_id,
                    twitch_login,
                    twitch_display_name,
                    access_token,
                    refresh_token,
                    expires_at,
                    scopes_json,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(purpose) DO UPDATE SET
                    twitch_user_id = excluded.twitch_user_id,
                    twitch_login = excluded.twitch_login,
                    twitch_display_name = excluded.twitch_display_name,
                    access_token = excluded.access_token,
                    refresh_token = excluded.refresh_token,
                    expires_at = excluded.expires_at,
                    scopes_json = excluded.scopes_json,
                    updated_at = excluded.updated_at
                """,
                (
                    purpose,
                    twitch_user_id,
                    twitch_login,
                    twitch_display_name,
                    access_token,
                    refresh_token,
                    expires_at,
                    json.dumps(scopes),
                    now_iso,
                ),
            )
            self.conn.commit()

    async def get_twitch_identity(self, purpose: str) -> Optional[Dict[str, Any]]:
        async with self.lock:
            row = self.conn.execute(
                "SELECT * FROM twitch_identities WHERE purpose = ?",
                (purpose,),
            ).fetchone()
            if not row:
                return None
            data = dict(row)
            data["scopes"] = json.loads(data.pop("scopes_json"))
            return data

    async def update_twitch_identity_tokens(
        self,
        *,
        purpose: str,
        access_token: str,
        refresh_token: str | None,
        expires_at: int,
        now_iso: str,
    ) -> None:
        async with self.lock:
            self.conn.execute(
                """
                UPDATE twitch_identities
                SET access_token = ?,
                    refresh_token = COALESCE(?, refresh_token),
                    expires_at = ?,
                    updated_at = ?
                WHERE purpose = ?
                """,
                (access_token, refresh_token, expires_at, now_iso, purpose),
            )
            self.conn.commit()

    async def increment_progress(
        self,
        *,
        discord_user_id: int,
        watch_points: int,
        message_points: int,
        new_level: int,
        now_iso: str,
    ) -> Dict[str, Any]:
        async with self.lock:
            row = self.conn.execute(
                "SELECT * FROM progress WHERE discord_user_id = ?",
                (str(discord_user_id),),
            ).fetchone()
            if row is None:
                self.conn.execute(
                    "INSERT INTO progress (discord_user_id, total_points, watch_points, message_points, level, updated_at) VALUES (?, 0, 0, 0, 0, ?)",
                    (str(discord_user_id), now_iso),
                )
                self.conn.commit()
                row = self.conn.execute(
                    "SELECT * FROM progress WHERE discord_user_id = ?",
                    (str(discord_user_id),),
                ).fetchone()

            old_total = int(row["total_points"])
            old_level = int(row["level"])
            total_gain = watch_points + message_points
            new_total = old_total + total_gain
            new_watch = int(row["watch_points"]) + watch_points
            new_message = int(row["message_points"]) + message_points

            self.conn.execute(
                """
                UPDATE progress
                SET total_points = ?,
                    watch_points = ?,
                    message_points = ?,
                    level = ?,
                    updated_at = ?
                WHERE discord_user_id = ?
                """,
                (new_total, new_watch, new_message, new_level, now_iso, str(discord_user_id)),
            )
            self.conn.commit()
            return {
                "discord_user_id": discord_user_id,
                "old_total": old_total,
                "new_total": new_total,
                "old_level": old_level,
                "new_level": new_level,
                "watch_points_gained": watch_points,
                "message_points_gained": message_points,
                "total_points_gained": total_gain,
                "total_watch_points": new_watch,
                "total_message_points": new_message,
            }

    async def get_progress(self, discord_user_id: int) -> Optional[Dict[str, Any]]:
        async with self.lock:
            row = self.conn.execute(
                "SELECT * FROM progress WHERE discord_user_id = ?",
                (str(discord_user_id),),
            ).fetchone()
            return dict(row) if row else None

    async def record_webhook_message(self, message_id: str, now_iso: str) -> bool:
        async with self.lock:
            existing = self.conn.execute(
                "SELECT 1 FROM processed_webhook_messages WHERE message_id = ?",
                (message_id,),
            ).fetchone()
            if existing:
                return False
            self.conn.execute(
                "INSERT INTO processed_webhook_messages (message_id, created_at) VALUES (?, ?)",
                (message_id, now_iso),
            )
            self.conn.commit()
            return True

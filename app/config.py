from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Dict, List

from dotenv import load_dotenv


load_dotenv()


def _require(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return int(value.strip())


def _split_scopes(value: str) -> List[str]:
    return [part for part in value.split() if part]


def _parse_role_map(raw: str) -> Dict[int, int]:
    if not raw.strip():
        return {}
    data = json.loads(raw)
    parsed: Dict[int, int] = {}
    for k, v in data.items():
        parsed[int(k)] = int(v)
    return dict(sorted(parsed.items(), key=lambda item: item[0]))


@dataclass(slots=True)
class Settings:
    discord_token: str
    discord_guild_id: int
    discord_bind_channel_id: int
    discord_announce_channel_id: int
    level_role_map: Dict[int, int]
    points_per_level: int
    announce_every_gain: bool

    public_base_url: str
    app_host: str
    app_port: int
    app_signing_secret: str

    twitch_client_id: str
    twitch_client_secret: str
    twitch_redirect_uri: str
    twitch_eventsub_secret: str

    viewer_link_scopes: List[str]
    twitch_bot_scopes: List[str]
    twitch_broadcaster_scopes: List[str]
    database_path: str



def load_settings() -> Settings:
    return Settings(
        discord_token=_require("DISCORD_TOKEN"),
        discord_guild_id=int(_require("DISCORD_GUILD_ID")),
        discord_bind_channel_id=int(_require("DISCORD_BIND_CHANNEL_ID")),
        discord_announce_channel_id=int(_require("DISCORD_ANNOUNCE_CHANNEL_ID")),
        level_role_map=_parse_role_map(os.getenv("LEVEL_ROLE_MAP_JSON", "{}")),
        points_per_level=_int("POINTS_PER_LEVEL", 100),
        announce_every_gain=_bool("ANNOUNCE_EVERY_GAIN", True),
        public_base_url=_require("PUBLIC_BASE_URL").rstrip("/"),
        app_host=os.getenv("APP_HOST", "0.0.0.0"),
        app_port=_int("APP_PORT", 8080),
        app_signing_secret=_require("APP_SIGNING_SECRET"),
        twitch_client_id=_require("TWITCH_CLIENT_ID"),
        twitch_client_secret=_require("TWITCH_CLIENT_SECRET"),
        twitch_redirect_uri=_require("TWITCH_REDIRECT_URI"),
        twitch_eventsub_secret=_require("TWITCH_EVENTSUB_SECRET"),
        viewer_link_scopes=_split_scopes(os.getenv("VIEWER_LINK_SCOPES", "user:read:email")),
        twitch_bot_scopes=_split_scopes(
            os.getenv("TWITCH_BOT_SCOPES", "user:read:chat user:bot moderator:read:chatters")
        ),
        twitch_broadcaster_scopes=_split_scopes(os.getenv("TWITCH_BROADCASTER_SCOPES", "channel:bot")),
        database_path=os.getenv("DATABASE_PATH", "bot_data.sqlite3"),
    )

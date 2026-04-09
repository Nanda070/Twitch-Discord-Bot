from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urlencode

import httpx

from app.config import Settings


class TwitchAPI:
    TOKEN_URL = "https://id.twitch.tv/oauth2/token"
    AUTHORIZE_URL = "https://id.twitch.tv/oauth2/authorize"
    HELIX_BASE = "https://api.twitch.tv/helix"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._app_token: Optional[str] = None
        self._app_token_expires_at: int = 0

    def build_authorize_url(self, *, state: str, scopes: List[str], force_verify: bool = True) -> str:
        params = {
            "client_id": self.settings.twitch_client_id,
            "redirect_uri": self.settings.twitch_redirect_uri,
            "response_type": "code",
            "scope": " ".join(scopes),
            "state": state,
            "force_verify": "true" if force_verify else "false",
        }
        return f"{self.AUTHORIZE_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str) -> Dict[str, Any]:
        data = {
            "client_id": self.settings.twitch_client_id,
            "client_secret": self.settings.twitch_client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": self.settings.twitch_redirect_uri,
        }
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(self.TOKEN_URL, data=data)
            response.raise_for_status()
            return response.json()

    async def refresh_user_token(self, refresh_token: str) -> Dict[str, Any]:
        data = {
            "client_id": self.settings.twitch_client_id,
            "client_secret": self.settings.twitch_client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(self.TOKEN_URL, data=data)
            response.raise_for_status()
            return response.json()

    async def get_app_access_token(self) -> str:
        now = int(time.time())
        if self._app_token and now < self._app_token_expires_at - 60:
            return self._app_token

        data = {
            "client_id": self.settings.twitch_client_id,
            "client_secret": self.settings.twitch_client_secret,
            "grant_type": "client_credentials",
        }
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(self.TOKEN_URL, data=data)
            response.raise_for_status()
            payload = response.json()

        self._app_token = payload["access_token"]
        self._app_token_expires_at = int(time.time()) + int(payload.get("expires_in", 0))
        return self._app_token

    async def get_authenticated_user(self, access_token: str) -> Dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Client-Id": self.settings.twitch_client_id,
        }
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(f"{self.HELIX_BASE}/users", headers=headers)
            response.raise_for_status()
            data = response.json().get("data", [])
            if not data:
                raise RuntimeError("Twitch /users returned empty data")
            return data[0]

    async def get_chatters(self, *, access_token: str, broadcaster_id: str, moderator_id: str) -> Set[str]:
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Client-Id": self.settings.twitch_client_id,
        }
        params: Dict[str, Any] = {
            "broadcaster_id": broadcaster_id,
            "moderator_id": moderator_id,
            "first": 1000,
        }
        users: Set[str] = set()
        async with httpx.AsyncClient(timeout=30) as client:
            while True:
                response = await client.get(f"{self.HELIX_BASE}/chat/chatters", headers=headers, params=params)
                response.raise_for_status()
                payload = response.json()
                for item in payload.get("data", []):
                    users.add(item["user_id"])
                cursor = payload.get("pagination", {}).get("cursor")
                if not cursor:
                    break
                params["after"] = cursor
        return users

    async def list_eventsub_subscriptions(self, app_access_token: str) -> List[Dict[str, Any]]:
        headers = {
            "Authorization": f"Bearer {app_access_token}",
            "Client-Id": self.settings.twitch_client_id,
        }
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(f"{self.HELIX_BASE}/eventsub/subscriptions", headers=headers)
            response.raise_for_status()
            return response.json().get("data", [])

    async def create_eventsub_subscription(self, app_access_token: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {app_access_token}",
            "Client-Id": self.settings.twitch_client_id,
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{self.HELIX_BASE}/eventsub/subscriptions",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            return response.json()

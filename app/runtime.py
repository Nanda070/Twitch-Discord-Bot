from __future__ import annotations

import asyncio
import hmac
import hashlib
import html
import secrets
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse

from app.config import Settings
from app.db import Database
from app.discord_bot import DiscordService
from app.oauth_state import StateSigner
from app.reward_engine import current_minute_key, points_to_level, previous_minute_key, seconds_until_next_minute
from app.twitch_api import TwitchAPI


UTC = timezone.utc


class BotRuntime:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.db = Database(settings.database_path)
        self.twitch = TwitchAPI(settings)
        self.state_signer = StateSigner(settings.app_signing_secret)
        self.discord = DiscordService(
            settings=settings,
            build_viewer_oauth_url=self.build_viewer_oauth_url,
            get_progress=self.db.get_progress,
            get_link=self.db.get_link_by_discord_user_id,
        )
        self.fastapi = FastAPI(title="Twitch Discord Points Bot")
        self.live = False
        self.message_flags: dict[str, set[str]] = {}
        self.minute_task: Optional[asyncio.Task[Any]] = None
        self._register_routes()

    @staticmethod
    def utc_now() -> datetime:
        return datetime.now(UTC)

    def build_state(self, *, purpose: str, discord_user_id: int | None = None, guild_id: int | None = None) -> str:
        payload: Dict[str, Any] = {
            "purpose": purpose,
            "nonce": secrets.token_hex(16),
            "exp": int(time.time()) + 900,
        }
        if discord_user_id is not None:
            payload["discord_user_id"] = discord_user_id
        if guild_id is not None:
            payload["guild_id"] = guild_id
        return self.state_signer.dumps(payload)

    def build_viewer_oauth_url(self, discord_user_id: int, guild_id: int) -> str:
        state = self.build_state(purpose="viewer", discord_user_id=discord_user_id, guild_id=guild_id)
        return self.twitch.build_authorize_url(state=state, scopes=self.settings.viewer_link_scopes)

    def build_admin_oauth_url(self, purpose: str) -> str:
        state = self.build_state(purpose=purpose)
        scopes = (
            self.settings.twitch_bot_scopes if purpose == "bot" else self.settings.twitch_broadcaster_scopes
        )
        return self.twitch.build_authorize_url(state=state, scopes=scopes)

    async def startup(self) -> None:
        await self.db.setup()
        self.minute_task = asyncio.create_task(self.minute_loop(), name="minute-loop")
        await self.ensure_eventsub_subscriptions()

    async def shutdown(self) -> None:
        if self.minute_task:
            self.minute_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.minute_task
        await self.discord.close()
        await self.db.close()

    async def ensure_identity_token(self, purpose: str) -> Optional[Dict[str, Any]]:
        identity = await self.db.get_twitch_identity(purpose)
        if not identity:
            return None
        if int(identity["expires_at"]) > int(time.time()) + 60:
            return identity
        refresh_token = identity.get("refresh_token")
        if not refresh_token:
            return identity

        refreshed = await self.twitch.refresh_user_token(refresh_token)
        now = self.utc_now().isoformat()
        await self.db.update_twitch_identity_tokens(
            purpose=purpose,
            access_token=refreshed["access_token"],
            refresh_token=refreshed.get("refresh_token", refresh_token),
            expires_at=int(time.time()) + int(refreshed.get("expires_in", 0)),
            now_iso=now,
        )
        return await self.db.get_twitch_identity(purpose)

    async def ensure_eventsub_subscriptions(self) -> None:
        bot_identity = await self.ensure_identity_token("bot")
        broadcaster_identity = await self.ensure_identity_token("broadcaster")
        if not bot_identity or not broadcaster_identity:
            return

        app_token = await self.twitch.get_app_access_token()
        existing = await self.twitch.list_eventsub_subscriptions(app_token)

        wanted = [
            {
                "type": "stream.online",
                "version": "1",
                "condition": {"broadcaster_user_id": broadcaster_identity["twitch_user_id"]},
            },
            {
                "type": "stream.offline",
                "version": "1",
                "condition": {"broadcaster_user_id": broadcaster_identity["twitch_user_id"]},
            },
            {
                "type": "channel.chat.message",
                "version": "1",
                "condition": {
                    "broadcaster_user_id": broadcaster_identity["twitch_user_id"],
                    "user_id": bot_identity["twitch_user_id"],
                },
            },
        ]

        def exists(candidate: Dict[str, Any]) -> bool:
            for item in existing:
                if item.get("type") != candidate["type"]:
                    continue
                if item.get("version") != candidate["version"]:
                    continue
                if item.get("condition") != candidate["condition"]:
                    continue
                if item.get("status") in {"enabled", "webhook_callback_verification_pending"}:
                    return True
            return False

        for candidate in wanted:
            if exists(candidate):
                continue
            payload = {
                **candidate,
                "transport": {
                    "method": "webhook",
                    "callback": f"{self.settings.public_base_url}/webhooks/twitch/eventsub",
                    "secret": self.settings.twitch_eventsub_secret,
                },
            }
            await self.twitch.create_eventsub_subscription(app_token, payload)

    def verify_twitch_signature(self, headers: dict[str, str], raw_body: bytes) -> bool:
        message_id = headers.get("twitch-eventsub-message-id", "")
        timestamp = headers.get("twitch-eventsub-message-timestamp", "")
        provided = headers.get("twitch-eventsub-message-signature", "")
        message = (message_id + timestamp).encode("utf-8") + raw_body
        expected = "sha256=" + hmac.new(
            self.settings.twitch_eventsub_secret.encode("utf-8"),
            message,
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, provided)

    async def handle_twitch_notification(self, body: Dict[str, Any]) -> None:
        subscription_type = body.get("subscription", {}).get("type")
        event = body.get("event", {})

        if subscription_type == "stream.online":
            self.live = True
            return

        if subscription_type == "stream.offline":
            self.live = False
            return

        if subscription_type == "channel.chat.message":
            chatter_user_id = event.get("chatter_user_id")
            if not chatter_user_id:
                return
            minute = current_minute_key()
            self.message_flags.setdefault(minute, set()).add(chatter_user_id)

    async def minute_loop(self) -> None:
        while True:
            await asyncio.sleep(seconds_until_next_minute())
            if not self.live:
                continue
            try:
                await self.finalize_previous_minute()
            except Exception as exc:  # pragma: no cover
                print(f"[minute-loop] error: {exc}")

    async def finalize_previous_minute(self) -> None:
        bot_identity = await self.ensure_identity_token("bot")
        broadcaster_identity = await self.ensure_identity_token("broadcaster")
        if not bot_identity or not broadcaster_identity:
            return

        chatters = await self.twitch.get_chatters(
            access_token=bot_identity["access_token"],
            broadcaster_id=broadcaster_identity["twitch_user_id"],
            moderator_id=bot_identity["twitch_user_id"],
        )
        msg_users = self.message_flags.pop(previous_minute_key(), set())
        links = await self.db.list_links()
        now_iso = self.utc_now().isoformat()

        for link in links:
            twitch_user_id = link["twitch_user_id"]
            discord_user_id = int(link["discord_user_id"])

            gained_watch = 1 if twitch_user_id in chatters else 0
            gained_message = 2 if twitch_user_id in msg_users else 0
            total_gain = gained_watch + gained_message
            if total_gain <= 0:
                continue

            current_progress = await self.db.get_progress(discord_user_id)
            current_total = int(current_progress["total_points"]) if current_progress else 0
            new_level = points_to_level(current_total + total_gain, self.settings.points_per_level)
            update = await self.db.increment_progress(
                discord_user_id=discord_user_id,
                watch_points=gained_watch,
                message_points=gained_message,
                new_level=new_level,
                now_iso=now_iso,
            )

            if self.settings.announce_every_gain:
                await self.discord.send_gain_embed(
                    discord_user_id=discord_user_id,
                    gained_total=update["total_points_gained"],
                    gained_watch=update["watch_points_gained"],
                    gained_message=update["message_points_gained"],
                    new_total=update["new_total"],
                    new_level=update["new_level"],
                )

            if update["new_level"] > update["old_level"]:
                role_name = await self.discord.sync_level_roles(
                    discord_user_id=discord_user_id,
                    level=update["new_level"],
                )
                await self.discord.send_levelup_embed(
                    discord_user_id=discord_user_id,
                    new_level=update["new_level"],
                    total_points=update["new_total"],
                    role_name=role_name,
                )

    def _register_routes(self) -> None:
        app = self.fastapi

        @app.on_event("startup")
        async def _startup() -> None:
            await self.startup()

        @app.get("/health")
        async def health() -> Dict[str, Any]:
            return {
                "ok": True,
                "live": self.live,
                "discord_ready": self.discord.is_ready(),
            }

        @app.get("/admin/twitch/start/{purpose}")
        async def admin_twitch_start(purpose: str) -> RedirectResponse:
            if purpose not in {"bot", "broadcaster"}:
                raise HTTPException(status_code=404, detail="Unknown setup purpose")
            return RedirectResponse(self.build_admin_oauth_url(purpose))

        @app.get("/oauth/twitch/callback")
        async def twitch_callback(
            code: str | None = None,
            state: str | None = None,
            error: str | None = None,
            error_description: str | None = None,
        ) -> HTMLResponse:
            if error:
                text = html.escape(error_description or error)
                return HTMLResponse(f"<h1>Twitch auth failed</h1><p>{text}</p>", status_code=400)
            if not code or not state:
                raise HTTPException(status_code=400, detail="Missing code or state")

            try:
                payload = self.state_signer.loads(state)
            except ValueError as exc:
                return HTMLResponse(f"<h1>Invalid state</h1><p>{html.escape(str(exc))}</p>", status_code=400)

            tokens = await self.twitch.exchange_code(code)
            user = await self.twitch.get_authenticated_user(tokens["access_token"])
            purpose = payload["purpose"]
            now_iso = self.utc_now().isoformat()
            expires_at = int(time.time()) + int(tokens.get("expires_in", 0))
            scope_list = tokens.get("scope", [])

            if purpose == "viewer":
                discord_user_id = int(payload["discord_user_id"])
                guild_id = int(payload["guild_id"])
                try:
                    discord_user = await self.discord.fetch_user(discord_user_id)
                    discord_username = str(discord_user)
                except Exception:
                    discord_username = str(discord_user_id)

                try:
                    await self.db.upsert_link(
                        discord_user_id=discord_user_id,
                        discord_username=discord_username,
                        guild_id=guild_id,
                        twitch_user_id=user["id"],
                        twitch_login=user["login"],
                        twitch_display_name=user["display_name"],
                        now_iso=now_iso,
                    )
                except ValueError as exc:
                    return HTMLResponse(
                        f"<h1>Link failed</h1><p>{html.escape(str(exc))}</p>",
                        status_code=409,
                    )

                return HTMLResponse(
                    (
                        "<h1>Twitch linked</h1>"
                        f"<p>Discord user <b>{html.escape(discord_username)}</b> is now linked to "
                        f"Twitch account <b>{html.escape(user['display_name'])}</b>.</p>"
                        "<p>You can close this page.</p>"
                    )
                )

            if purpose in {"bot", "broadcaster"}:
                await self.db.save_twitch_identity(
                    purpose=purpose,
                    twitch_user_id=user["id"],
                    twitch_login=user["login"],
                    twitch_display_name=user["display_name"],
                    access_token=tokens["access_token"],
                    refresh_token=tokens.get("refresh_token"),
                    expires_at=expires_at,
                    scopes=scope_list,
                    now_iso=now_iso,
                )
                try:
                    await self.ensure_eventsub_subscriptions()
                except Exception as exc:
                    return HTMLResponse(
                        (
                            f"<h1>{html.escape(purpose.title())} auth saved</h1>"
                            f"<p>But EventSub sync failed: {html.escape(str(exc))}</p>"
                        ),
                        status_code=500,
                    )
                return HTMLResponse(
                    (
                        f"<h1>{html.escape(purpose.title())} auth saved</h1>"
                        f"<p>Twitch account <b>{html.escape(user['display_name'])}</b> has been stored.</p>"
                        "<p>EventSub sync finished. You can close this page.</p>"
                    )
                )

            return HTMLResponse("<h1>Unknown auth purpose</h1>", status_code=400)

        @app.post("/webhooks/twitch/eventsub")
        async def twitch_eventsub(request: Request) -> PlainTextResponse | JSONResponse:
            raw_body = await request.body()
            headers = {k.lower(): v for k, v in request.headers.items()}
            if not self.verify_twitch_signature(headers, raw_body):
                raise HTTPException(status_code=403, detail="Bad signature")

            payload = await request.json()
            message_type = headers.get("twitch-eventsub-message-type", "")
            if message_type == "webhook_callback_verification":
                return PlainTextResponse(payload["challenge"])
            if message_type == "revocation":
                return JSONResponse({"ok": True, "revoked": True})

            message_id = headers.get("twitch-eventsub-message-id", "")
            if message_id:
                accepted = await self.db.record_webhook_message(message_id, self.utc_now().isoformat())
                if not accepted:
                    return JSONResponse({"ok": True, "duplicate": True})

            await self.handle_twitch_notification(payload)
            return JSONResponse({"ok": True})

    async def run(self) -> None:
        config = uvicorn.Config(
            app=self.fastapi,
            host=self.settings.app_host,
            port=self.settings.app_port,
            loop="asyncio",
            log_level="info",
        )
        server = uvicorn.Server(config)
        await asyncio.gather(
            self.discord.start(self.settings.discord_token),
            server.serve(),
        )


import contextlib  # noqa: E402

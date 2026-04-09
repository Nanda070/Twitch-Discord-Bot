from __future__ import annotations

from typing import Awaitable, Callable, Optional

import discord
from discord import app_commands
from discord.ext import commands

from app.config import Settings

BuildViewerLink = Callable[[int, int], str]
ReadProgress = Callable[[int], Awaitable[dict | None]]
ReadLink = Callable[[int], Awaitable[dict | None]]


class BindView(discord.ui.View):
    def __init__(
        self,
        *,
        build_viewer_oauth_url: BuildViewerLink,
    ) -> None:
        super().__init__(timeout=None)
        self.build_viewer_oauth_url = build_viewer_oauth_url

    @discord.ui.button(
        label="Привязать Twitch",
        style=discord.ButtonStyle.primary,
        custom_id="twitch_bind:start",
        emoji="🔗",
    )
    async def start_bind(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "Эта кнопка работает только внутри сервера.",
                ephemeral=True,
            )
            return

        url = self.build_viewer_oauth_url(interaction.user.id, interaction.guild.id)
        embed = discord.Embed(
            title="Привязка Twitch",
            description=(
                "Нажми по ссылке ниже и авторизуй Twitch-аккаунт.\n\n"
                f"[Подключить Twitch]({url})"
            ),
        )
        embed.set_footer(text="Ссылка персональная и действует ограниченное время")
        await interaction.response.send_message(embed=embed, ephemeral=True)


class DiscordService(commands.Bot):
    def __init__(
        self,
        *,
        settings: Settings,
        build_viewer_oauth_url: BuildViewerLink,
        get_progress: ReadProgress,
        get_link: ReadLink,
    ) -> None:
        intents = discord.Intents.default()
        intents.guilds = True
        intents.members = True

        super().__init__(command_prefix="!", intents=intents)
        self.settings = settings
        self._build_viewer_oauth_url = build_viewer_oauth_url
        self._get_progress = get_progress
        self._get_link = get_link
        self.bind_view = BindView(build_viewer_oauth_url=build_viewer_oauth_url)

    async def setup_hook(self) -> None:
        self.add_view(self.bind_view)

        guild = discord.Object(id=self.settings.discord_guild_id)

        @self.tree.command(name="send_bind_panel", description="Send the Twitch bind panel", guild=guild)
        @app_commands.default_permissions(administrator=True)
        async def send_bind_panel(interaction: discord.Interaction) -> None:
            channel = self.get_channel(self.settings.discord_bind_channel_id)
            if channel is None:
                channel = await self.fetch_channel(self.settings.discord_bind_channel_id)
            if not isinstance(channel, discord.TextChannel):
                await interaction.response.send_message("Bind channel is not a text channel.", ephemeral=True)
                return
            await self.post_bind_panel(channel)
            await interaction.response.send_message("Bind panel sent.", ephemeral=True)

        @self.tree.command(name="progress", description="Show your Twitch stream progress", guild=guild)
        async def progress(interaction: discord.Interaction) -> None:
            progress_data = await self._get_progress(interaction.user.id)
            link_data = await self._get_link(interaction.user.id)
            if not link_data:
                await interaction.response.send_message(
                    "У тебя еще нет привязки Twitch. Нажми кнопку в канале привязки.",
                    ephemeral=True,
                )
                return

            embed = discord.Embed(title="Твой Twitch прогресс")
            embed.add_field(name="Twitch", value=link_data["twitch_display_name"], inline=False)
            if progress_data:
                embed.add_field(name="Всего points", value=str(progress_data["total_points"]), inline=True)
                embed.add_field(name="Watch points", value=str(progress_data["watch_points"]), inline=True)
                embed.add_field(name="Message points", value=str(progress_data["message_points"]), inline=True)
                embed.add_field(name="Level", value=str(progress_data["level"]), inline=True)
            else:
                embed.description = "Пока нет начислений."
            await interaction.response.send_message(embed=embed, ephemeral=True)

        await self.tree.sync(guild=guild)

    async def on_ready(self) -> None:
        print(f"Discord bot logged in as {self.user} ({self.user.id if self.user else 'n/a'})")

    async def post_bind_panel(self, channel: discord.TextChannel) -> None:
        embed = discord.Embed(
            title="Привязка Twitch к Discord",
            description=(
                "Привяжи Twitch-аккаунт, чтобы получать points за стрим.\n\n"
                "Правила начисления:\n"
                "• +1 point за присутствие на стриме в минуту\n"
                "• +2 points за минимум одно сообщение в чат за минуту"
            ),
        )
        embed.set_footer(text="После привязки начисления и роли будут идти автоматически")
        await channel.send(embed=embed, view=self.bind_view)

    async def _get_announce_channel(self) -> Optional[discord.TextChannel]:
        channel = self.get_channel(self.settings.discord_announce_channel_id)
        if channel is None:
            channel = await self.fetch_channel(self.settings.discord_announce_channel_id)
        return channel if isinstance(channel, discord.TextChannel) else None

    async def send_gain_embed(
        self,
        *,
        discord_user_id: int,
        gained_total: int,
        gained_watch: int,
        gained_message: int,
        new_total: int,
        new_level: int,
    ) -> None:
        channel = await self._get_announce_channel()
        if channel is None:
            return
        embed = discord.Embed(
            title="Начисление points",
            description=f"<@{discord_user_id}> получил **+{gained_total}** points",
        )
        embed.add_field(name="За просмотр", value=f"+{gained_watch}", inline=True)
        embed.add_field(name="За сообщения", value=f"+{gained_message}", inline=True)
        embed.add_field(name="Всего", value=str(new_total), inline=True)
        embed.add_field(name="Level", value=str(new_level), inline=True)
        embed.set_footer(text="Twitch Progress System")
        await channel.send(embed=embed)

    async def send_levelup_embed(
        self,
        *,
        discord_user_id: int,
        new_level: int,
        total_points: int,
        role_name: str | None,
    ) -> None:
        channel = await self._get_announce_channel()
        if channel is None:
            return
        embed = discord.Embed(
            title="Новый уровень",
            description=f"<@{discord_user_id}> достиг уровня **{new_level}**",
        )
        embed.add_field(name="Общий points", value=str(total_points), inline=True)
        embed.add_field(name="Награда", value=role_name or "Нет", inline=True)
        embed.set_footer(text="Twitch Progress System")
        await channel.send(embed=embed)

    async def sync_level_roles(self, *, discord_user_id: int, level: int) -> str | None:
        guild = self.get_guild(self.settings.discord_guild_id)
        if guild is None:
            guild = await self.fetch_guild(self.settings.discord_guild_id)

        member = guild.get_member(discord_user_id)
        if member is None:
            try:
                member = await guild.fetch_member(discord_user_id)
            except discord.NotFound:
                return None

        target_role_id: int | None = None
        for required_level, role_id in self.settings.level_role_map.items():
            if level >= required_level:
                target_role_id = role_id

        configured_role_ids = set(self.settings.level_role_map.values())
        current_tracked_roles = [role for role in member.roles if role.id in configured_role_ids]

        roles_to_remove = [role for role in current_tracked_roles if role.id != target_role_id]
        if roles_to_remove:
            await member.remove_roles(*roles_to_remove, reason="Twitch level sync")

        role_name: str | None = None
        if target_role_id is not None:
            target_role = guild.get_role(target_role_id)
            if target_role is None:
                fetched_roles = await guild.fetch_roles()
                target_role = next((role for role in fetched_roles if role.id == target_role_id), None)
            if target_role is not None:
                role_name = target_role.name
                if target_role not in member.roles:
                    await member.add_roles(target_role, reason="Twitch level reward")

        return role_name

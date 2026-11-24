"""Twitch quote submissions to a configured Discord destination."""
import re
import time
from datetime import datetime, timezone

import discord
from redbot.core import commands

from .errors import BridgeError
from .permissions import staff_only
from .policy import chat_text, twitch_level

QUOTE_DEFAULTS = {"enabled": False, "channel": None, "permission": "moderator",
                  "mode": "embed", "color": 0x5865F2, "cooldown": 10}
COLORS = {"blue": 0x3498DB, "green": 0x2ECC71, "red": 0xE74C3C,
          "purple": 0x9B59B6, "orange": 0xE67E22, "yellow": 0xF1C40F,
          "gold": 0xF1C40F, "pink": 0xEB459E, "white": 0xFFFFFF, "black": 0x000000,
          "blurple": 0x5865F2}


def quote_color(value):
    value = value.strip().lower()
    if value in COLORS:
        return COLORS[value]
    value = value.removeprefix("#").removeprefix("0x")
    if not re.fullmatch(r"[0-9a-f]{6}", value):
        raise ValueError("Use a color name (blue, green, red, purple, orange, yellow, gold, pink, white, black, blurple) or a six-digit hex color such as #5865F2.")
    return int(value, 16)


def quote_settings(cfg):
    return {**QUOTE_DEFAULTS, **cfg.get("quote_settings", {})}


class QuotesMixin:
    def _quote_channel(self, guild, settings):
        channel = guild.get_channel(settings["channel"]) if guild and settings["channel"] else None
        if not isinstance(channel, discord.TextChannel) or channel.guild.id != guild.id:
            raise BridgeError("Configure an accessible text channel with twitchquote channel first.")
        permissions = channel.permissions_for(guild.me)
        if not permissions.view_channel or not permissions.send_messages:
            raise BridgeError("Paimon needs View Channel and Send Messages in the quote channel.")
        if settings["mode"] == "embed" and not permissions.embed_links:
            raise BridgeError("Paimon needs Embed Links in the quote channel, or use message mode.")
        return channel

    async def _edit_quote(self, ctx, **updates):
        try:
            async with self.settings_lock:
                group = self.config.guild(ctx.guild)
                cfg = await group.all()
                settings = quote_settings(cfg)
                settings.update(updates)
                if settings["enabled"] and (not cfg["enabled"] or not cfg["broadcaster_id"]):
                    raise BridgeError("Link and enable this server's Twitch connection first.")
                if settings["enabled"] or "channel" in updates:
                    self._quote_channel(ctx.guild, settings)
                await group.quote_settings.set(settings)
            await ctx.send("Quote settings saved.")
        except BridgeError as exc:
            await ctx.send(str(exc))

    @staff_only()
    @commands.guild_only()
    @commands.group(name="twitchquote", invoke_without_command=True)
    async def twitchquote(self, ctx):
        """Configure !quote submissions from this server's linked Twitch channel."""
        await ctx.send_help()

    @twitchquote.command(name="channel")
    async def quote_channel(self, ctx, channel: discord.TextChannel):
        if channel.guild.id != ctx.guild.id:
            await ctx.send("Choose a channel in this server.")
            return
        await self._edit_quote(ctx, channel=channel.id)

    @twitchquote.command(name="enabled")
    async def quote_enabled(self, ctx, enabled: bool):
        await self._edit_quote(ctx, enabled=enabled)

    @twitchquote.command(name="permission")
    async def quote_permission(self, ctx, permission: str):
        permission = permission.lower()
        if permission not in ("everyone", "moderator", "broadcaster"):
            await ctx.send("Choose everyone, moderator, or broadcaster.")
            return
        await self._edit_quote(ctx, permission=permission)

    @twitchquote.command(name="mode")
    async def quote_mode(self, ctx, mode: str):
        mode = mode.lower()
        if mode == "chat":
            mode = "message"
        if mode not in ("message", "embed"):
            await ctx.send("Choose message (plain chat) or embed.")
            return
        await self._edit_quote(ctx, mode=mode)

    @twitchquote.command(name="color")
    async def quote_set_color(self, ctx, color: str):
        try:
            color = quote_color(color)
        except ValueError as exc:
            await ctx.send(str(exc))
            return
        await self._edit_quote(ctx, color=color)

    @twitchquote.command(name="cooldown")
    async def quote_cooldown(self, ctx, seconds: int):
        if not 0 <= seconds <= 86400:
            await ctx.send("Choose 0-86400 seconds.")
            return
        await self._edit_quote(ctx, cooldown=seconds)

    @twitchquote.command(name="status")
    async def quote_status(self, ctx):
        cfg = await self.config.guild(ctx.guild).all()
        settings = quote_settings(cfg)
        destination = f"<#{settings['channel']}>" if settings["channel"] else "Not set"
        await ctx.send(f"Quotes enabled: {settings['enabled']} | Channel: {destination} | "
                       f"Twitch permission: {settings['permission']} | Mode: {settings['mode']} | "
                       f"Color: #{settings['color']:06X} | Cooldown: {settings['cooldown']}s | Timestamp: UTC",
                       allowed_mentions=discord.AllowedMentions.none())

    async def _post_quote(self, guild_id, broadcaster_id, event, text):
        text = chat_text(text)
        async with self.settings_lock:
            cfg = await self.config.guild_from_id(guild_id).all()
            settings = quote_settings(cfg)
            if not cfg["enabled"] or cfg["broadcaster_id"] != broadcaster_id:
                raise BridgeError("The Twitch connection is paused or the broadcaster changed.")
            if not settings["enabled"]:
                raise BridgeError("Quote submissions are not enabled for this channel.")
            required = {"everyone": 0, "moderator": 1, "broadcaster": 2}[settings["permission"]]
            if twitch_level(event) < required:
                raise BridgeError("You do not have permission to submit quotes on this channel.")
            guild = self.bot.get_guild(guild_id)
            if guild is None or await self.bot.cog_disabled_in_guild(self, guild):
                raise BridgeError("Quote posting is unavailable in the linked Discord server.")
            channel = self._quote_channel(guild, settings)
            key = (guild_id, "quote")
            now = time.monotonic()
            if now < self.cooldowns.get(key, 0):
                raise BridgeError("A quote was submitted recently; wait for the cooldown.")
            login = event.get("chatter_user_login", "")
            if not re.fullmatch(r"[a-zA-Z0-9_]{1,25}", login):
                raise BridgeError("The quote submitter's Twitch username is unavailable.")
            stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            footer = f"Submitted by @{login} | {stamp}"
            try:
                if settings["mode"] == "embed":
                    embed = discord.Embed(description=text, color=settings["color"])
                    embed.set_footer(text=footer)
                    await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
                else:
                    await channel.send(text + "\n\n" + footer,
                                       allowed_mentions=discord.AllowedMentions.none(), suppress_embeds=True)
            except discord.HTTPException:
                raise BridgeError("Discord could not accept the quote. Check channel permissions and try again.") from None
            self.cooldowns[key] = time.monotonic() + settings["cooldown"]
        return "Quote sent to Discord."

"""Moderator stream metadata updates using the linked broadcaster's token."""
import re

import discord
from redbot.core import commands

from .errors import BridgeError
from .permissions import staff_only

API = "https://api.twitch.tv/helix/"
CHANNEL_COMMANDS = {"title", "game", "category", "tags", "language"}


def title_text(value):
    text = " ".join(value.split())
    if not text or len(text) > 140 or any(ord(c) < 32 for c in text):
        raise ValueError("Use a nonempty stream title of at most 140 characters.")
    return text


def channel_tags(value):
    if value.strip().lower() == "clear":
        return []
    tags = value.replace(",", " ").split()
    if not tags or len(tags) > 10 or any(len(tag) > 25 or not tag.isalnum() for tag in tags):
        raise ValueError("Use up to 10 alphanumeric tags, each up to 25 characters. Use clear to remove all tags.")
    if len({tag.casefold() for tag in tags}) != len(tags):
        raise ValueError("Each stream tag must be unique.")
    return tags


class ChannelEditMixin:
    async def _read_channel(self, guild_id, expected=None):
        cfg = await self.config.guild_from_id(guild_id).all()
        bid = cfg["broadcaster_id"]
        if not cfg["enabled"] or not bid or (expected is not None and bid != expected):
            raise BridgeError("The Twitch connection is paused or the broadcaster changed.")
        client_id, auth = await self._token()
        code, body = await self._request("GET", API + "channels", params={"broadcaster_id": bid},
            headers={"Client-Id": client_id, "Authorization": "Bearer " + auth["access_token"]})
        if code != 200 or not body.get("data"):
            raise BridgeError("Could not read this broadcaster's channel information.")
        return body["data"][0]

    async def _resolve_category(self, query):
        query = query.strip()
        if not query or len(query) > 100:
            raise ValueError("Use a category name or a numeric Twitch category ID.")
        client_id, auth = await self._token()
        headers = {"Client-Id": client_id, "Authorization": "Bearer " + auth["access_token"]}
        if query.isascii() and query.isdecimal():
            code, body = await self._request("GET", API + "games", params={"id": query}, headers=headers)
        else:
            code, body = await self._request("GET", API + "search/categories", params={"query": query, "first": 100}, headers=headers)
        if code != 200:
            raise BridgeError("Twitch category lookup failed. Try again later.")
        matches = body.get("data", [])
        if not matches:
            raise ValueError("No Twitch category matched. Use its full name or category ID.")
        exact = [item for item in matches if item["name"].casefold() == query.casefold() or item["id"] == query]
        if len(exact) == 1:
            return exact[0]
        if len(matches) == 1:
            return matches[0]
        options = "; ".join(f"{item['name']} (ID {item['id']})" for item in matches[:5])
        raise ValueError(("Several categories matched. Use a full name or ID: " + options)[:500])

    async def _update_channel(self, guild_id, fields, *, expected, level):
        if level < 1:
            raise BridgeError("Only moderators and the broadcaster can change stream information.")
        async with self.settings_lock:
            cfg = await self.config.guild_from_id(guild_id).all()
            if not cfg["enabled"] or cfg["broadcaster_id"] != expected:
                raise BridgeError("The Twitch connection is paused or the broadcaster changed.")
            client_id, auth = await self._role_token(guild_id, {"channel:manage:broadcast"})
            if auth.get("user_id") != expected:
                raise BridgeError("The update must be authorized by this channel's broadcaster.")
            code, _ = await self._request("PATCH", API + "channels", params={"broadcaster_id": expected}, json=fields,
                headers={"Client-Id": client_id, "Authorization": "Bearer " + auth["access_token"]})
            if code != 204:
                raise BridgeError(f"Twitch rejected the channel update (HTTP {code}). Check broadcaster authorization and field values.")
            self.stream_cache.pop(guild_id, None)
            self.tools_wakeup.set()

    async def _channel_action(self, guild_id, field, value, level, expected=None):
        cfg = await self.config.guild_from_id(guild_id).all()
        bid = cfg["broadcaster_id"]
        if not cfg["enabled"] or not bid or (expected is not None and bid != expected):
            raise BridgeError("The Twitch connection is paused or the broadcaster changed.")
        field = "category" if field == "game" else field
        if level < 1:
            raise BridgeError("Only moderators and the broadcaster can use stream information commands.")
        if not value.strip():
            channel = await self._read_channel(guild_id, expected=bid)
            if field == "title":
                return "Stream title: " + channel.get("title", "Not set")
            if field == "category":
                return "Stream category: " + (channel.get("game_name") or "Not set")
            if field == "tags":
                return "Stream tags: " + (", ".join(channel.get("tags", [])) or "None")
            return "Stream language: " + channel.get("broadcaster_language", "Not set")
        if level < 1:
            raise BridgeError("Only moderators and the broadcaster can change stream information.")
        if field == "title":
            title = title_text(value)
            fields, reply = {"title": title}, "Stream title updated: " + title
        elif field == "category":
            category = await self._resolve_category(value)
            fields, reply = {"game_id": category["id"]}, "Stream category updated: " + category["name"]
        elif field == "tags":
            tags = channel_tags(value)
            fields, reply = {"tags": tags}, "Stream tags updated: " + (", ".join(tags) or "None")
        elif field == "language":
            language = value.strip().lower()
            if not re.fullmatch(r"[a-z]{2}|other", language):
                raise ValueError("Use a two-letter language code such as en, or other.")
            fields, reply = {"broadcaster_language": language}, "Stream language updated: " + language
        else:
            raise ValueError("Choose title, category, tags, or language.")
        await self._update_channel(guild_id, fields, expected=bid, level=level)
        return reply

    @staff_only()
    @commands.guild_only()
    @commands.group(name="tstream", invoke_without_command=True)
    async def tstream(self, ctx):
        """Moderator controls for this server's Twitch title/category/tags/language."""
        await ctx.send_help()

    async def _channel_reply(self, ctx, field, value):
        try:
            text = await self._channel_action(ctx.guild.id, field, value, await self._discord_level(ctx))
            await ctx.send(text, allowed_mentions=discord.AllowedMentions.none(), suppress_embeds=True)
        except (BridgeError, ValueError) as exc:
            await ctx.send(str(exc), allowed_mentions=discord.AllowedMentions.none(), suppress_embeds=True)

    @tstream.command(name="title")
    async def stream_title(self, ctx, *, title: str = ""):
        """Show the title, or set it when text is provided."""
        await self._channel_reply(ctx, "title", title)

    @tstream.command(name="category", aliases=["game"])
    async def stream_category(self, ctx, *, category: str = ""):
        """Show/set a game or category by name or Twitch ID."""
        await self._channel_reply(ctx, "category", category)

    @tstream.command(name="tags")
    async def stream_tags(self, ctx, *, tags: str = ""):
        """Show/set tags, or use clear to remove them."""
        await self._channel_reply(ctx, "tags", tags)

    @tstream.command(name="language")
    async def stream_language(self, ctx, language: str = ""):
        """Show/set a supported two-letter stream language."""
        await self._channel_reply(ctx, "language", language)

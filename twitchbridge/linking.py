"""Persistent Discord panels and identity-only Twitch device approvals."""
import asyncio
import contextlib
import secrets
import time

import discord

from .errors import BridgeError
from .policy import twitch_target

OAUTH = "https://id.twitch.tv/oauth2/"
PANEL_CUSTOM_ID = "paimon:twitchbridge:member-link:v1"


class LinkModal(discord.ui.Modal):
    def __init__(self, cog, guild_id, user_id, panel):
        super().__init__(title="Link your Twitch account", timeout=300)
        self.cog, self.guild_id, self.user_id, self.panel = cog, guild_id, user_id, panel
        self.username = discord.ui.TextInput(label="Twitch username", placeholder="Your Twitch username", max_length=25)
        self.add_item(self.username)

    async def on_submit(self, interaction):
        try:
            if interaction.user.id != self.user_id or interaction.guild_id != self.guild_id:
                await interaction.response.send_message("This prompt belongs to another member or server.", ephemeral=True)
                return
            await interaction.response.defer(ephemeral=True, thinking=True)
            await self.cog._begin_device_link(interaction, str(self.username), self.panel)
        except (BridgeError, ValueError) as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
        except (KeyError, TypeError):
            await interaction.followup.send("Twitch returned an unexpected response. Click the button to retry.", ephemeral=True)
        finally:
            self.cog.link_modals.discard(self)
            self.stop()

    async def on_timeout(self):
        self.cog.link_modals.discard(self)


class LinkPanelView(discord.ui.View):
    def __init__(self, cog, label="Link Twitch account"):
        super().__init__(timeout=None)
        self.cog = cog
        button = discord.ui.Button(label=label, style=discord.ButtonStyle.primary, custom_id=PANEL_CUSTOM_ID)
        button.callback = self.open_link
        self.add_item(button)

    async def open_link(self, interaction):
        try:
            panel = await self.cog._check_link_panel(interaction)
            links = await self.cog.config.guild_from_id(interaction.guild_id).member_links()
            if str(interaction.user.id) in links:
                await interaction.response.send_message("Your Twitch account is already linked in this server.", ephemeral=True)
                return
            # Expiring modals also have a global cap to prevent unbounded UI state.
            if len(self.cog.link_modals) >= 1000:
                raise BridgeError("Too many link prompts are open. Try again shortly.")
            modal = LinkModal(self.cog, interaction.guild_id, interaction.user.id, panel)
            self.cog.link_modals.add(modal)
            try:
                await interaction.response.send_modal(modal)
            except discord.HTTPException:
                self.cog.link_modals.discard(modal)
                modal.stop()
                raise
        except BridgeError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)


class LinkingMixin:
    async def _restore_link_panels(self):
        for guild_id, cfg in (await self.config.all_guilds()).items():
            panel = cfg.get("link_panel", {})
            if panel.get("message_id"):
                view = LinkPanelView(self, cfg.get("link_panel_label", "Link Twitch account"))
                self.bot.add_view(view, message_id=panel["message_id"])
                self.link_views[guild_id] = view

    async def _check_link_panel(self, interaction, expected=None):
        if self.closing or interaction.guild is None or interaction.user.bot:
            raise BridgeError("Linking is unavailable here.")
        if await self.bot.cog_disabled_in_guild(self, interaction.guild):
            raise BridgeError("Twitch linking is disabled in this server.")
        if not await self.bot.allowed_by_whitelist_blacklist(interaction.user):
            raise BridgeError("You cannot use this bot right now.")
        cfg = await self.config.guild_from_id(interaction.guild_id).all()
        panel = cfg.get("link_panel", {})
        candidate = expected if expected is not None else {
            "message_id": interaction.message.id if interaction.message else None,
            "channel_id": interaction.channel_id,
        }
        if (not panel or panel.get("message_id") != candidate.get("message_id")
                or panel.get("channel_id") != candidate.get("channel_id")
                or interaction.channel_id != panel.get("channel_id")):
            raise BridgeError("This linking panel is no longer active. Use the current panel.")
        if not cfg["enabled"] or not cfg["broadcaster_id"]:
            raise BridgeError("This server's Twitch connection is paused or not configured.")
        return dict(panel)

    async def _store_identity_link_locked(self, guild_id, discord_id, twitch_id, login):
        group = self.config.guild_from_id(guild_id)
        links = await group.member_links()
        if any(uid != str(discord_id) and item["twitch_id"] == twitch_id for uid, item in links.items()):
            raise BridgeError("That Twitch account is already linked to another Discord member here.")
        current = links.get(str(discord_id))
        if current and current["twitch_id"] != twitch_id:
            raise BridgeError("You already have a different linked Twitch account here.")
        guild = self.bot.get_guild(guild_id)
        if guild is None:
            raise BridgeError("The Discord server is unavailable.")
        try:
            user = guild.get_member(discord_id) or await guild.fetch_member(discord_id)
        except discord.HTTPException:
            raise BridgeError("You must still be a member of this Discord server.") from None
        links[str(discord_id)] = {"twitch_id": twitch_id, "login": login, "linked_at": time.time()}
        await group.member_links.set(links)
        if getattr(self, "role_wakeup", None) is not None:
            self.role_wakeup.set()
        return user

    async def _begin_device_link(self, interaction, username, panel):
        await self._check_link_panel(interaction, expected=panel)
        key = (interaction.guild_id, interaction.user.id)
        async with self.settings_lock:
            now = time.monotonic()
            self.link_attempts = {k: t for k, t in self.link_attempts.items() if now - t < 15}
            if now - self.link_attempts.get(key, -60) < 15:
                raise BridgeError("Wait 15 seconds before requesting another link.")
            if key in self.member_auth_tasks and not self.member_auth_tasks[key].done():
                raise BridgeError("Your Twitch approval is already pending. Use the previous private link.")
            if sum(not task.done() for task in self.member_auth_tasks.values()) >= 1000:
                raise BridgeError("Too many link requests are pending. Try again shortly.")
            self.link_attempts[key] = now
            cfg = await self.config.guild_from_id(key[0]).all()
            generation = self.link_generation.get(key, 0)
            broadcaster_id = cfg["broadcaster_id"]
            starter = asyncio.current_task()
            self.member_auth_tasks[key] = starter
        try:
            await self._issue_member_device(interaction, username, panel, key, generation, broadcaster_id)
        finally:
            if self.member_auth_tasks.get(key) is starter:
                self.member_auth_tasks.pop(key, None)

    async def _issue_member_device(self, interaction, username, panel, key, generation, broadcaster_id):
        # Public lookup binds the typed username to its permanent ID before approval.
        identity = await self._lookup_twitch(twitch_target(username))
        client_id = await self._client_id()
        code, device = await self._request("POST", OAUTH + "device", data={"client_id": client_id, "scope": ""})
        if code != 200:
            raise BridgeError("Twitch could not start identity approval. Try again later.")
        async with self.settings_lock:
            await self._check_link_panel(interaction, expected=panel)
            cfg = await self.config.guild_from_id(key[0]).all()
            if self.link_generation.get(key, 0) != generation or cfg["broadcaster_id"] != broadcaster_id:
                raise BridgeError("Link settings changed. Start again from the panel.")
            if str(key[1]) in cfg.get("member_links", {}):
                raise BridgeError("You already have a linked Twitch account here.")
            nonce = secrets.token_urlsafe(16)
            pending = {"nonce": nonce, "generation": generation, "twitch_id": identity["id"],
                       "login": identity["login"], "broadcaster_id": broadcaster_id, "panel": dict(panel)}
            self.pending_device_links[key] = pending
            self.pending_links.pop(key, None)
            task = asyncio.create_task(self._poll_member_device(interaction, client_id, device, pending))
            self.member_auth_tasks[key] = task
        try:
            await interaction.followup.send(
                f"Sign into **{identity['login']}** and approve your Twitch identity here:\n"
                f"{device['verification_uri']}\nCode: `{device['user_code']}`\n"
                "This private link expires in 10 minutes. No chat commands or DMs are required.", ephemeral=True)
        except discord.HTTPException:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            raise

    async def _poll_member_device(self, interaction, client_id, device, pending):
        key = (interaction.guild_id, interaction.user.id)
        access_token = None
        try:
            interval = max(1, device["interval"])
            deadline = time.monotonic() + min(600, device["expires_in"])
            while time.monotonic() < deadline:
                await asyncio.sleep(interval)
                if time.monotonic() >= deadline:
                    break
                code, data = await self._request("POST", OAUTH + "token", data={
                    "client_id": client_id, "device_code": device["device_code"],
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code"})
                if code == 200:
                    access_token = data["access_token"]
                    break
                error = data.get("message", data.get("error", ""))
                if error == "authorization_pending":
                    continue
                if error == "slow_down":
                    interval += 5
                    continue
                raise BridgeError("Twitch approval was denied or expired. Click the linking button to retry.")
            if access_token is None:
                raise BridgeError("Twitch approval expired. Click the linking button to retry.")
            code, identity = await self._request("GET", OAUTH + "validate", headers={"Authorization": "OAuth " + access_token})
            if (code != 200 or identity.get("client_id") != client_id
                    or identity.get("user_id") != pending["twitch_id"]):
                raise BridgeError("The approved Twitch account did not match the username you entered. Nothing was linked.")
            async with self.settings_lock:
                current = self.pending_device_links.get(key)
                cfg = await self.config.guild_from_id(key[0]).all()
                if (self.closing or current is not pending
                        or self.link_generation.get(key, 0) != pending["generation"]
                        or cfg.get("link_panel") != pending["panel"]
                        or not cfg["enabled"] or cfg["broadcaster_id"] != pending["broadcaster_id"]
                        or await self._client_id() != client_id):
                    raise BridgeError("The linking request was cancelled or server settings changed. Start again.")
                await self._check_link_panel(interaction, expected=pending["panel"])
                await self._store_identity_link_locked(key[0], key[1], identity["user_id"], identity["login"])
            await interaction.followup.send("Your Twitch account is verified and linked. Your server roles will update if role syncing is enabled.", ephemeral=True)
        except (BridgeError, KeyError, TypeError, ValueError) as exc:
            text = str(exc) if isinstance(exc, BridgeError) else "Twitch returned an unexpected response. Start again."
            with contextlib.suppress(discord.HTTPException):
                await interaction.followup.send(text, ephemeral=True)
        except discord.HTTPException:
            pass
        finally:
            async with self.settings_lock:
                if self.pending_device_links.get(key) is pending:
                    self.pending_device_links.pop(key, None)
            # Only identity is retained; never keep member access or refresh tokens.
            if access_token:
                with contextlib.suppress(BridgeError):
                    await self._request("POST", OAUTH + "revoke", data={"client_id": client_id, "token": access_token})
            if self.member_auth_tasks.get(key) is asyncio.current_task():
                self.member_auth_tasks.pop(key, None)

    async def _cancel_device_link(self, guild_id, user_id):
        key = (guild_id, user_id)
        task = self.member_auth_tasks.get(key)
        if task and task is not asyncio.current_task():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        async with self.settings_lock:
            self.pending_device_links.pop(key, None)
            if self.member_auth_tasks.get(key) is task:
                self.member_auth_tasks.pop(key, None)
            self.link_generation[key] = self.link_generation.get(key, 0) + 1

    async def _update_link_panel(self, guild):
        cfg = await self.config.guild(guild).all()
        panel = cfg.get("link_panel", {})
        if not panel:
            return
        channel = guild.get_channel(panel["channel_id"])
        if not isinstance(channel, discord.TextChannel):
            raise BridgeError("The linking panel channel is unavailable. Post a new panel.")
        try:
            message = await channel.fetch_message(panel["message_id"])
            view = self.link_views.get(guild.id)
            if view is None:
                view = LinkPanelView(self, cfg["link_panel_label"])
            else:
                view.children[0].label = cfg["link_panel_label"]
            await message.edit(content=cfg["link_panel_text"], view=view, allowed_mentions=discord.AllowedMentions.none())
            self.link_views[guild.id] = view
        except discord.HTTPException:
            raise BridgeError("Could not update the panel. Check the message and channel permissions.") from None

    async def _remove_link_panel(self, guild):
        async with self.settings_lock:
            group = self.config.guild(guild)
            panel = await group.link_panel()
            await group.link_panel.set({})
        view = self.link_views.pop(guild.id, None)
        if view:
            view.stop()
        for key in list(self.member_auth_tasks):
            if key[0] == guild.id:
                await self._cancel_device_link(*key)
        if panel:
            channel = guild.get_channel(panel["channel_id"])
            if channel:
                with contextlib.suppress(discord.HTTPException):
                    message = await channel.fetch_message(panel["message_id"])
                    await message.edit(view=None)

"""Verified member identities, broadcaster-specific roles, and shoutout text."""
import asyncio
import contextlib
import secrets
import time

import discord
from redbot.core import commands

from .errors import BridgeError
from .linking import LinkingMixin, LinkPanelView
from .policy import parse_command, twitch_target, shoutout_text, chat_text, twitch_level

API = "https://api.twitch.tv/helix/"
OAUTH = "https://id.twitch.tv/oauth2/"
ROLE_SCOPES = {"moderator": "moderation:read", "subscriber": "channel:read:subscriptions",
               "vip": "channel:read:vips", "broadcaster": None}
DEFAULT_SHOUTOUT = "Go follow {user} at {url}!"


class CommunityMixin(LinkingMixin):
    async def _lookup_twitch(self, target):
        login = twitch_target(target)
        client_id, auth = await self._token()
        code, body = await self._request("GET", API + "users", params={"login": login},
            headers={"Client-Id": client_id, "Authorization": "Bearer " + auth["access_token"]})
        if code != 200 or not body.get("data"):
            raise BridgeError("Twitch account not found, or Twitch could not verify it.")
        return body["data"][0]

    async def _complete_member_link(self, guild_id, broadcaster_id, event, code):
        user = None
        async with self.settings_lock:
            now = time.monotonic()
            match = next(((key, value) for key, value in self.pending_links.items()
                          if key[0] == guild_id and value["code"] == code), None)
            if not match:
                return False
            key, pending = match
            cfg = await self.config.guild_from_id(guild_id).all()
            if (pending["expires"] <= now or not cfg["enabled"]
                    or cfg["broadcaster_id"] != broadcaster_id
                    or pending["broadcaster_id"] != broadcaster_id
                    or pending["twitch_id"] != event.get("chatter_user_id")):
                return False
            guild = self.bot.get_guild(guild_id)
            if guild is None:
                return False
            try:
                user = guild.get_member(key[1]) or await guild.fetch_member(key[1])
            except discord.HTTPException:
                return False
            links = cfg.get("member_links", {})
            if any(uid != str(key[1]) and item["twitch_id"] == pending["twitch_id"] for uid, item in links.items()):
                return False
            current = links.get(str(key[1]))
            if current and current["twitch_id"] != pending["twitch_id"]:
                return False
            links[str(key[1])] = {"twitch_id": pending["twitch_id"],
                "login": event.get("chatter_user_login", pending["login"]), "linked_at": time.time()}
            await self.config.guild_from_id(guild_id).member_links.set(links)
            self.pending_links.pop(key, None)
        if getattr(self, "role_wakeup", None) is not None:
            self.role_wakeup.set()
        with contextlib.suppress(discord.HTTPException):
            await user.send("Your Twitch account is verified and linked in this Discord server. Crate inventories were not changed.")
        return True

    @commands.guild_only()
    @commands.group(name="twitchlink", invoke_without_command=True)
    async def twitchlink(self, ctx, username: str = None):
        """Link your own Twitch account using a private, short-lived chat challenge."""
        if not username:
            await ctx.send_help()
            return
        key = (ctx.guild.id, ctx.author.id)
        now = time.monotonic()
        async with self.settings_lock:
            self.pending_links = {k: v for k, v in self.pending_links.items() if v["expires"] > now}
            if now - self.link_attempts.get(key, -60) < 15:
                await ctx.send("Wait 15 seconds before requesting another link code.")
                return
            if len(self.pending_links) >= 1000:
                await ctx.send("Too many pending link requests. Try again shortly.")
                return
            # Bound the attempt cache independently of pending challenges.
            self.link_attempts = {k: t for k, t in self.link_attempts.items() if now - t < 15}
            self.link_attempts[key] = now
        try:
            identity = await self._lookup_twitch(username)
            async with self.settings_lock:
                cfg = await self.config.guild(ctx.guild).all()
                if self.link_attempts.get(key) != now:
                    raise BridgeError("This link request was cancelled. Start again when ready.")
                if not cfg["enabled"] or not cfg["broadcaster_id"]:
                    raise BridgeError("This server needs an enabled Twitch connection before you can link.")
                links = cfg.get("member_links", {})
                if str(ctx.author.id) in links:
                    raise BridgeError("You already have a linked account here. Use twitchlink unlink before changing it.")
                if any(item["twitch_id"] == identity["id"] for item in links.values()):
                    raise BridgeError("That Twitch account is already linked to another Discord member here.")
                challenge = {"code": secrets.token_urlsafe(12), "expires": time.monotonic() + 600,
                    "twitch_id": identity["id"], "login": identity["login"], "broadcaster_id": cfg["broadcaster_id"]}
                # Publish the pending request before sending the DM. A failed DM clears it.
                if len(self.pending_links) >= 1000 and key not in self.pending_links:
                    raise BridgeError("Too many pending link requests. Try again shortly.")
                self.pending_links[key] = challenge
                instruction = f"{cfg.get('command_prefix', '!')}link {challenge['code']}"
                await ctx.author.send(
                    f"To link **{identity['login']}** in **{discord.utils.escape_markdown(ctx.guild.name)}**, "
                    f"sign into that Twitch account and post the following in https://twitch.tv/{cfg['broadcaster']} "
                    f"within 10 minutes:\n`{instruction}`\nDo not share this code or approve requests you did not start."
                )
            await ctx.send("Check your DMs for the Twitch account verification instructions.")
        except (BridgeError, ValueError) as exc:
            await ctx.send(str(exc), allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            async with self.settings_lock:
                self.pending_links.pop(key, None)
            await ctx.send("Enable DMs from me, then request a new link code.")

    @twitchlink.command(name="status")
    async def link_status(self, ctx):
        """Show your own linked Twitch account in this server."""
        links = await self.config.guild(ctx.guild).member_links()
        link = links.get(str(ctx.author.id))
        await ctx.send(f"Linked Twitch account: {link['login']}" if link else "You have no linked Twitch account in this server.",
                       allowed_mentions=discord.AllowedMentions.none())

    async def _unlink_member(self, guild_id, discord_id):
        await self._cancel_device_link(guild_id, discord_id)
        async with self.settings_lock:
            self.pending_links.pop((guild_id, discord_id), None)
            self.link_attempts.pop((guild_id, discord_id), None)
            group = self.config.guild_from_id(guild_id)
            links = await group.member_links()
            links.pop(str(discord_id), None)
            await group.member_links.set(links)
            guild = self.bot.get_guild(guild_id)
            if guild:
                await self._cleanup_roles_locked(guild, only_user=discord_id)

    @twitchlink.command(name="unlink")
    async def unlink(self, ctx):
        """Remove your link and roles granted by this integration; no inventory changes."""
        await self._unlink_member(ctx.guild.id, ctx.author.id)
        await ctx.send("Your link and pending verification were removed. Integration-granted roles are removed where permissions allow; failures remain queued for cleanup.")

    async def _role_token(self, guild_id, required):
        # Called under settings_lock, including token rotation and writeback.
        group = self.config.guild_from_id(guild_id)
        cfg = await group.all()
        auth = cfg.get("role_auth", {})
        client_id = await self._client_id()
        if (not auth or auth.get("client_id") != client_id
                or auth.get("user_id") != cfg["broadcaster_id"]):
            raise BridgeError("Run twitchroles authorize as this server's broadcaster first.")
        if auth["expires_at"] < time.time() + 120:
            code, body = await self._request("POST", OAUTH + "token", data={"client_id": client_id,
                "grant_type": "refresh_token", "refresh_token": auth["refresh_token"]})
            if code != 200:
                raise BridgeError("Broadcaster role authorization expired. Run twitchroles authorize again.")
            auth.update(access_token=body["access_token"], refresh_token=body["refresh_token"],
                        expires_at=time.time() + body["expires_in"], validated_at=0)
            await group.role_auth.set(auth)
        if time.time() - auth.get("validated_at", 0) >= 3600:
            code, body = await self._request("GET", OAUTH + "validate", headers={"Authorization": "OAuth " + auth["access_token"]})
            if (code != 200 or body.get("user_id") != cfg["broadcaster_id"] or body.get("client_id") != client_id):
                raise BridgeError("Broadcaster role authorization is invalid. Re-authorize it.")
            auth.update(scopes=body.get("scopes", []), validated_at=time.time())
            await group.role_auth.set(auth)
        if not required.issubset(auth.get("scopes", [])):
            raise BridgeError("Role mappings need additional permissions. Run twitchroles authorize again.")
        return client_id, auth

    async def _fetch_role_users(self, endpoint, headers, broadcaster_id, user_ids=None):
        result, cursor, visited = set(), None, set()
        while True:
            params = [("broadcaster_id", broadcaster_id), ("first", "100")]
            if user_ids:
                params.extend(("user_id", uid) for uid in user_ids)
            if cursor:
                params.append(("after", cursor))
            code, body = await self._request("GET", API + endpoint, headers=headers, params=params)
            if code != 200 or not isinstance(body.get("data"), list):
                raise BridgeError(f"Twitch role lookup failed (HTTP {code}). No roles were changed.")
            result.update(item["user_id"] for item in body["data"])
            cursor = body.get("pagination", {}).get("cursor")
            if not cursor:
                return result
            if cursor in visited:
                raise BridgeError("Twitch returned incomplete role data. No roles were changed.")
            visited.add(cursor)

    @staticmethod
    def _manageable_role(guild, role):
        return (role is not None and not role.is_default() and not role.managed
                and not role.permissions.administrator and guild.me is not None
                and guild.me.guild_permissions.manage_roles and role < guild.me.top_role)

    async def _cleanup_roles_locked(self, guild, only_user=None, all_roles=False):
        group = self.config.guild(guild)
        cfg = await group.all()
        managed = cfg.get("managed_roles", {})
        links = cfg.get("member_links", {})
        for uid, role_ids in list(managed.items()):
            if only_user is not None and uid != str(only_user):
                continue
            if not all_roles and only_user is None and uid in links:
                continue
            member = guild.get_member(int(uid))
            if member is None:
                try:
                    member = await guild.fetch_member(int(uid))
                except discord.NotFound:
                    managed.pop(uid, None)
                    continue
                except discord.HTTPException:
                    continue
            for rid in list(role_ids):
                role = guild.get_role(rid)
                if role is None or role not in member.roles:
                    role_ids.remove(rid)
                    continue
                if not self._manageable_role(guild, role):
                    continue
                try:
                    await member.remove_roles(role, reason="Twitch link removed or role-sync cleanup")
                    role_ids.remove(rid)
                except discord.HTTPException:
                    continue
            if not role_ids:
                managed.pop(uid, None)
        await group.managed_roles.set(managed)

    async def _sync_roles(self, guild):
        async with self.settings_lock:
            group = self.config.guild(guild)
            cfg = await group.all()
            await self._cleanup_roles_locked(guild, all_roles=not cfg["broadcaster_id"])
            if cfg.get("role_auth"):
                # Maintain stored OAuth sessions even while mappings are paused or idle.
                await self._role_token(guild.id, set())
            if not cfg.get("roles_enabled") or not cfg["enabled"]:
                return "Role sync is paused. Unlinked-member cleanup was attempted."
            links, mappings = cfg.get("member_links", {}), cfg.get("role_mappings", {})
            if not mappings:
                await self._cleanup_roles_locked(guild, all_roles=True)
                return "No role mappings; tracked grants were cleaned up where possible."
            if not links:
                return "No linked members to sync."
            required = {ROLE_SCOPES[k] for k in mappings if ROLE_SCOPES[k]}
            client_id, auth = await self._role_token(guild.id, required)
            headers = {"Client-Id": client_id, "Authorization": "Bearer " + auth["access_token"]}
            statuses = {"broadcaster": {cfg["broadcaster_id"]}}
            if "moderator" in mappings:
                statuses["moderator"] = await self._fetch_role_users("moderation/moderators", headers, cfg["broadcaster_id"])
            if "vip" in mappings:
                statuses["vip"] = await self._fetch_role_users("channels/vips", headers, cfg["broadcaster_id"])
            if "subscriber" in mappings:
                statuses["subscriber"] = set()
                ids = sorted({item["twitch_id"] for item in links.values()})
                for start in range(0, len(ids), 100):
                    statuses["subscriber"].update(await self._fetch_role_users("subscriptions", headers, cfg["broadcaster_id"], ids[start:start + 100]))
            # All lookups succeeded before any status-based role removal.
            cfg = await group.all()
            managed = cfg.get("managed_roles", {})
            changes, failures = 0, 0
            for uid, link in links.items():
                member = guild.get_member(int(uid))
                if member is None:
                    try:
                        member = await guild.fetch_member(int(uid))
                    except discord.HTTPException:
                        failures += 1
                        continue
                desired = {rid for kind, rid in mappings.items() if link["twitch_id"] in statuses.get(kind, set())}
                owned = set(managed.get(uid, []))
                current = {role.id for role in member.roles}
                for rid in desired - current:
                    role = guild.get_role(rid)
                    if not self._manageable_role(guild, role):
                        failures += 1
                        continue
                    try:
                        await member.add_roles(role, reason="Verified Twitch status")
                        owned.add(rid)
                        changes += 1
                        managed[uid] = sorted(owned)
                        await group.managed_roles.set(managed)
                    except discord.HTTPException:
                        failures += 1
                for rid in owned - desired:
                    role = guild.get_role(rid)
                    if role is None or rid not in current:
                        owned.discard(rid)
                    elif self._manageable_role(guild, role):
                        try:
                            await member.remove_roles(role, reason="Twitch status no longer qualifies")
                            owned.discard(rid)
                            changes += 1
                        except discord.HTTPException:
                            failures += 1
                    else:
                        failures += 1
                if owned:
                    managed[uid] = sorted(owned)
                else:
                    managed.pop(uid, None)
                await group.managed_roles.set(managed)
            return f"Role sync complete: {changes} change(s), {failures} unavailable member/role or permission failure(s)."

    async def _role_loop(self):
        await self.bot.wait_until_red_ready()
        while True:
            self.role_wakeup.clear()
            for gid, cfg in (await self.config.all_guilds()).items():
                if not cfg.get("roles_enabled") and not cfg.get("managed_roles") and not cfg.get("role_auth"):
                    continue
                guild = self.bot.get_guild(gid)
                if guild is None:
                    continue
                try:
                    self.role_status[gid] = await self._sync_roles(guild)
                except BridgeError as exc:
                    self.role_status[gid] = str(exc)
                except (KeyError, TypeError, ValueError, discord.HTTPException):
                    self.role_status[gid] = "Role sync failed; check permissions and broadcaster authorization."
            try:
                await asyncio.wait_for(self.role_wakeup.wait(), timeout=900)
            except asyncio.TimeoutError:
                pass

    @commands.is_owner()
    @commands.guild_only()
    @commands.group(name="twitchroles", invoke_without_command=True)
    async def twitchroles(self, ctx):
        """Configure Twitch-to-Discord roles for this broadcaster's server."""
        await ctx.send_help()

    @twitchroles.command(name="map")
    async def role_map(self, ctx, status: str, role: discord.Role):
        """Map moderator, subscriber, vip, or broadcaster to a Discord role."""
        status = status.lower()
        if status not in ROLE_SCOPES:
            await ctx.send("Choose moderator, subscriber, vip, or broadcaster.")
            return
        if role.guild.id != ctx.guild.id or not self._manageable_role(ctx.guild, role):
            await ctx.send("Choose a non-administrator role below Paimon's highest role, with Manage Roles enabled for Paimon.")
            return
        async with self.settings_lock:
            async with self.config.guild(ctx.guild).role_mappings() as mappings:
                mappings[status] = role.id
        await ctx.send("Role mapping saved. Authorize the broadcaster, then enable/sync roles.")

    @twitchroles.command(name="unmap")
    async def role_unmap(self, ctx, status: str):
        """Remove a mapping; tracked grants are removed on the next enabled sync."""
        async with self.settings_lock:
            async with self.config.guild(ctx.guild).role_mappings() as mappings:
                mappings.pop(status.lower(), None)
        await ctx.send("Mapping removed. Use twitchroles cleanup to remove all tracked grants immediately.")

    @twitchroles.command(name="authorize")
    async def role_authorize(self, ctx):
        """Authorize broadcaster-only status lookups via DM."""
        expected = await self.config.guild(ctx.guild).broadcaster()
        if not expected:
            await ctx.send("Select and verify a broadcaster first.")
            return
        await self._start_auth(ctx, ctx.guild.id, expected, purpose="roles")

    @twitchroles.command(name="enabled")
    async def roles_enabled(self, ctx, enabled: bool):
        """Opt in or pause automatic role changes; pausing preserves roles."""
        async with self.settings_lock:
            await self.config.guild(ctx.guild).roles_enabled.set(enabled)
        await ctx.send("Role sync enabled; run twitchroles sync now, or wait up to 15 minutes." if enabled else "Role sync paused. Existing roles are preserved; cleanup removes tracked grants.")

    @twitchroles.command(name="sync")
    async def roles_sync(self, ctx):
        """Run a role check now."""
        try:
            result = await self._sync_roles(ctx.guild)
        except BridgeError as exc:
            result = str(exc)
        self.role_status[ctx.guild.id] = result
        await ctx.send(result)

    @twitchroles.command(name="cleanup")
    async def roles_cleanup(self, ctx):
        """Pause syncing and remove all integration-owned grants where possible."""
        async with self.settings_lock:
            await self.config.guild(ctx.guild).roles_enabled.set(False)
            await self._cleanup_roles_locked(ctx.guild, all_roles=True)
            remaining = await self.config.guild(ctx.guild).managed_roles()
        await ctx.send(f"Sync paused. Cleanup attempted; {len(remaining)} member(s) still need role/permission cleanup.")

    @twitchroles.command(name="status")
    async def roles_status(self, ctx):
        cfg = await self.config.guild(ctx.guild).all()
        await ctx.send(f"Enabled: {cfg.get('roles_enabled', False)} | Linked members: {len(cfg.get('member_links', {}))}\n"
                       f"Mappings (status: role ID): {cfg.get('role_mappings', {})}\n"
                       f"Last check: {self.role_status.get(ctx.guild.id, 'Not run yet')}",
                       allowed_mentions=discord.AllowedMentions.none())

    async def _shoutout(self, guild_id, target, expected_broadcaster=None):
        identity = await self._lookup_twitch(target)
        async with self._command_lock(guild_id):
            cfg = await self.config.guild_from_id(guild_id).all()
            if not cfg["enabled"]:
                raise BridgeError("The Twitch connection is paused.")
            if expected_broadcaster is not None and cfg["broadcaster_id"] != expected_broadcaster:
                raise BridgeError("The broadcaster changed before this shoutout could be sent.")
            now = time.monotonic()
            if now < self.shoutout_cooldowns.get(guild_id, 0):
                raise BridgeError("A shoutout was sent recently. Wait for its cooldown.")
            text = shoutout_text(cfg.get("shoutout_message", DEFAULT_SHOUTOUT), identity, cfg["broadcaster"])
            self.shoutout_cooldowns[guild_id] = now + cfg.get("shoutout_cooldown", 60)
            broadcaster_id = cfg["broadcaster_id"]
        await self._send_twitch(guild_id, text, expected_broadcaster=broadcaster_id)
        return text

    @commands.mod_or_permissions(manage_guild=True)
    @commands.guild_only()
    @commands.command(name="twitchshoutout")
    async def twitchshoutout(self, ctx, target: str):
        """Post a follow message for a Twitch username or channel URL."""
        try:
            text = await self._shoutout(ctx.guild.id, target)
            await ctx.send(f"Shoutout sent: {text}", allowed_mentions=discord.AllowedMentions.none(), suppress_embeds=True)
        except (BridgeError, ValueError) as exc:
            await ctx.send(str(exc))



    @twitchroles.command(name="panel")
    async def link_panel(self, ctx, channel: discord.TextChannel):
        """Post the persistent member-link button in a channel in this server."""
        if channel.guild.id != ctx.guild.id:
            await ctx.send("Choose a text channel in this server.")
            return
        permissions = channel.permissions_for(ctx.guild.me)
        if not permissions.view_channel or not permissions.send_messages:
            await ctx.send("I need View Channel and Send Messages in that channel.")
            return
        cfg = await self.config.guild(ctx.guild).all()
        if not cfg["enabled"] or not cfg["broadcaster_id"]:
            await ctx.send("Enable and verify this server's Twitch connection first.")
            return
        # Send first; an unsuccessful new post must not remove the existing panel.
        view = LinkPanelView(self, cfg.get("link_panel_label", "Link Twitch account"))
        try:
            message = await channel.send(cfg.get("link_panel_text", "Link your Twitch account to receive your server roles."),
                view=view, allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            view.stop()
            await ctx.send("Could not post the linking panel. Check channel permissions.")
            return
        await self._remove_link_panel(ctx.guild)
        async with self.settings_lock:
            await self.config.guild(ctx.guild).link_panel.set({"channel_id": channel.id, "message_id": message.id})
            self.link_views[ctx.guild.id] = view
        await ctx.send("Twitch linking panel posted. Members can click it without typing commands.")

    @twitchroles.command(name="paneltext")
    async def link_panel_text(self, ctx, *, text: str):
        """Set the panel message text and update an existing panel."""
        if not text.strip() or len(text) > 2000:
            await ctx.send("Use 1-2000 characters for the panel message.")
            return
        await self.config.guild(ctx.guild).link_panel_text.set(text)
        try:
            await self._update_link_panel(ctx.guild)
            await ctx.send("Linking panel text saved.")
        except BridgeError as exc:
            await ctx.send(str(exc))

    @twitchroles.command(name="panellabel")
    async def link_panel_label(self, ctx, *, label: str):
        """Set the linking button label and update an existing panel."""
        label = label.strip()
        if not label or len(label) > 80:
            await ctx.send("Use 1-80 characters for the button label.")
            return
        await self.config.guild(ctx.guild).link_panel_label.set(label)
        try:
            await self._update_link_panel(ctx.guild)
            await ctx.send("Linking button label saved.")
        except BridgeError as exc:
            await ctx.send(str(exc))

    @twitchroles.command(name="panelremove")
    async def link_panel_remove(self, ctx):
        """Deactivate the panel and cancel its pending account approvals."""
        await self._remove_link_panel(ctx.guild)
        await ctx.send("Linking panel removed and pending panel approvals cancelled.")

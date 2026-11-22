"""Twitch-owned ad schedules and explicitly requested ad operations."""
import asyncio
import time
from .errors import BridgeError

API = "https://api.twitch.tv/helix/"
AD_DEFAULTS = {"enabled": False, "leads": [300], "message": "Ads start in {ad_seconds} seconds for about {ad_duration} seconds.", "mode": "chat"}


class AdsMixin:
    async def _ad_api(self, gid, method, path, scope, body=None, expected=None):
        async with self.settings_lock:
            cfg = await self.config.guild_from_id(gid).all()
            if not cfg["enabled"] or not cfg["broadcaster_id"] or (expected is not None and cfg["broadcaster_id"] != expected):
                raise BridgeError("The Twitch connection changed or is paused.")
            client_id, auth = await self._role_token(gid, {scope})
            kwargs = {"headers": {"Client-Id": client_id, "Authorization": "Bearer " + auth["access_token"]}}
            if body is None:
                kwargs["params"] = {"broadcaster_id": cfg["broadcaster_id"]}
            else:
                kwargs["json"] = dict(body, broadcaster_id=cfg["broadcaster_id"])
            code, result = await self._request(method, API + path, **kwargs)
            if code != 200 or not result.get("data"):
                raise BridgeError(f"Twitch ad request failed (HTTP {code}). Check eligibility, permissions, cooldown and snoozes.")
            return cfg["broadcaster_id"], result["data"][0]

    async def _refresh_ads(self, gid, expected=None):
        async with self.ad_locks.setdefault(gid, asyncio.Lock()):
            bid, schedule = await self._ad_api(gid, "GET", "channels/ads", "channel:read:ads", expected=expected)
            self.ad_cache[gid] = dict(schedule, broadcaster_id=bid, fetched=time.monotonic())
            return self.ad_cache[gid]

    async def _ad_action(self, gid, action, seconds=60, expected=None):
        async with self.ad_locks.setdefault(gid, asyncio.Lock()):
            if time.monotonic() < self.ad_retry_after.get((gid, action), 0):
                raise BridgeError("Wait for Twitch's ad cooldown before trying again.")
            if action == "run" and seconds not in (30, 60, 90, 120, 150, 180):
                raise ValueError("Choose a commercial length of 30, 60, 90, 120, 150 or 180 seconds.")
            self.ad_pending.add(gid)
            self.ad_cache.pop(gid, None)
            self.ad_retry_after[(gid, action)] = time.monotonic() + 10
            try:
                if action == "snooze":
                    bid, result = await self._ad_api(gid, "POST", "channels/ads/schedule/snooze", "channel:manage:ads", expected=expected)
                    self.ad_cache[gid] = dict(result, broadcaster_id=bid, fetched=time.monotonic())
                    self.ad_pause_until[gid] = time.time() + 300
                    await self.config.guild_from_id(gid).ad_warning_pause_until.set(self.ad_pause_until[gid])
                    text = f"Twitch snoozed the next ad by five minutes. Snoozes left: {result.get('snooze_count', 0)}."
                else:
                    info = await self._stream_info(gid, force=True)
                    if not info["stream"]:
                        raise BridgeError("The broadcaster must be live to run a commercial.")
                    bid, result = await self._ad_api(gid, "POST", "channels/commercial", "channel:edit:commercial", body={"length": seconds}, expected=expected)
                    self.ad_retry_after[(gid, action)] = time.monotonic() + result.get("retry_after", 480)
                    text = f"Twitch started a {result.get('length', seconds)}-second commercial."
                try:
                    _, schedule = await self._ad_api(gid, "GET", "channels/ads", "channel:read:ads", expected=bid)
                    self.ad_cache[gid] = dict(schedule, broadcaster_id=bid, fetched=time.monotonic())
                    at = schedule.get("next_ad_at", 0)
                    text += f" Next ad in {max(0, int(at - time.time()))} seconds." if at else " Twitch has no next ad scheduled."
                except BridgeError:
                    text += " Schedule refresh is pending; the ad action itself succeeded."
                self.tools_wakeup.set()
                return text
            finally:
                self.ad_pending.discard(gid)

    async def _reserve_ad_notice(self, gid, at, lead):
        async with self._tool_lock(gid):
            group = self.config.guild_from_id(gid)
            notices = await group.ad_notices()
            bid = (await group.all())["broadcaster_id"]
            key = f"{bid}:{at}"
            if notices.get("at") != key:
                notices = {"at": key, "leads": []}
            if lead in notices["leads"]:
                return False
            notices["leads"].append(lead)
            await group.ad_notices.set(notices)
            return True

"""Parameterized response variables and bounded public HTTP lookups."""
import asyncio
import calendar
import ipaddress
import json
import random
import re
import shlex
import socket
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode, urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import aiohttp
from .errors import BridgeError

DYNAMIC_NAMES = {"countdown", "random", "randomreply", "choose", "urlfetch", "time", "weather", "followage"}
# Only randomreply permits the nested {roll} marker; its result is still literal text.
DYNAMIC = re.compile(
    r"\{(randomreply(?:\s+(?:[^{}]|\{roll\})*)?|"
    r"(?:countdown|random|choose|urlfetch|time|weather)(?:\s+[^{}]*)?|followage)\}")
FIXED_ZONES = {"UTC": 0, "GMT": 0, "EST": -5, "EDT": -4, "CST": -6, "CDT": -5,
               "MST": -7, "MDT": -6, "PST": -8, "PDT": -7}


def zone(value):
    if value in FIXED_ZONES:
        return timezone(timedelta(hours=FIXED_ZONES[value]), value)
    try:
        return ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError("Unknown timezone; use a location such as Europe/Helsinki.") from None


def calendar_duration(start, end):
    """Full calendar months, then whole weeks/days/hours; never negative."""
    end = end.astimezone(start.tzinfo)
    if end <= start:
        return "0 months, 0 weeks, 0 days, 0 hours"
    months = (end.year - start.year) * 12 + end.month - start.month
    def anchor(n):
        year, month = divmod(start.year * 12 + start.month - 1 + n, 12)
        return start.replace(year=year, month=month + 1,
            day=min(start.day, calendar.monthrange(year, month + 1)[1]))
    if anchor(months) > end:
        months -= 1
    hours = int((end.astimezone(timezone.utc) - anchor(months).astimezone(timezone.utc)).total_seconds() // 3600)
    days, hours = divmod(max(0, hours), 24)
    weeks, days = divmod(days, 7)
    return ", ".join(f"{number} {unit}{'' if number == 1 else 's'}"
                     for number, unit in [(months, "month"), (weeks, "week"), (days, "day"), (hours, "hour")])


def parse_variable(body):
    try:
        parts = shlex.split(body)
    except ValueError:
        raise ValueError("Variable has an unclosed quote.") from None
    if not parts or parts[0] not in DYNAMIC_NAMES:
        raise ValueError("Unknown response variable.")
    name, args = parts[0], parts[1:]
    if name == "choose" and not args:
        raise ValueError('Use {choose "Response A" "Response B"}.')
    if name == "random":
        if len(args) != 2 or not all(re.fullmatch(r"-?\d{1,10}", a) for a in args) or int(args[0]) > int(args[1]):
            raise ValueError("Use {random 1 100}, with the lower number first.")
    if name == "randomreply":
        if not args or len(args) % 2:
            raise ValueError('Use {randomreply 10 "A" 80 "B" 100 "C"}.')
        previous = 0
        for threshold in args[::2]:
            if not re.fullmatch(r"\d{1,9}", threshold) or int(threshold) <= previous:
                raise ValueError("Random reply thresholds must be positive and strictly increasing.")
            previous = int(threshold)
    if name in {"time", "urlfetch"} and len(args) != 1:
        raise ValueError(f"Use {{{name} value}}.")
    if name == "time":
        zone(args[0])
    if name == "urlfetch":
        public_url(args[0])
    if name == "weather" and (not args or len(" ".join(args)) > 150):
        raise ValueError("Use {weather Helsinki/Finland}.")
    if name == "countdown":
        countdown_target(args)
    if name == "followage" and args:
        raise ValueError("Use {followage} without arguments.")
    return name, args


def countdown_target(args, now=None):
    if len(args) < 3:
        raise ValueError("Use {countdown dec 25 12:00:00 AM America/Toronto}, optionally including a year.")
    tz = zone(args[-1])
    value = " ".join(args[:-1])

    def local_target(value):
        target = value.replace(tzinfo=tz)
        # Reject nonexistent times during spring DST; autumn uses the first occurrence.
        if target.astimezone(timezone.utc).astimezone(tz).replace(tzinfo=None) != target.replace(tzinfo=None):
            raise ValueError("That local time does not exist due to daylight saving time.")
        return target

    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %I:%M:%S %p", "%b %d %Y %I:%M:%S %p", "%B %d %Y %I:%M:%S %p"):
        try:
            parsed = datetime.strptime(value, fmt)
        except ValueError:
            continue
        return local_target(parsed)

    # Parse with a leap-year anchor so February 29 is a valid annual date.
    for fmt in ("%m-%d %H:%M:%S", "%m-%d %I:%M:%S %p", "%b %d %H:%M:%S", "%B %d %H:%M:%S",
                "%b %d %I:%M:%S %p", "%B %d %I:%M:%S %p"):
        try:
            parsed = datetime.strptime("2000 " + value, "%Y " + fmt)
        except ValueError:
            continue
        current = (now or datetime.now(timezone.utc)).astimezone(tz)
        for year in range(current.year, min(current.year + 9, 10000)):
            try:
                candidate = parsed.replace(year=year)
            except ValueError:
                continue  # February 29 resumes at the next leap year.
            if candidate <= current.replace(tzinfo=None):
                continue
            return local_target(candidate)
        raise ValueError("No future occurrence can be represented for this countdown.")
    raise ValueError("Invalid countdown date or time; use dec 25 [year] 12:00:00 AM timezone.")


def public_url(value):
    try:
        url = urlsplit(value)
        if (url.scheme != "https" or not url.hostname or url.username or url.password
                or url.port not in (None, 443) or url.fragment or any(c.isspace() or ord(c) < 32 for c in value)):
            raise ValueError()
        try:
            address = ipaddress.ip_address(url.hostname)
        except ValueError:
            if url.hostname.lower() == "localhost" or url.hostname.lower().endswith((".localhost", ".local")):
                raise ValueError()
        else:
            if not address.is_global:
                raise ValueError()
    except ValueError:
        raise ValueError("URL fetch requires a public HTTPS URL on port 443 without credentials or a fragment.") from None
    return value


class PublicResolver:
    async def resolve(self, host, port=0, family=socket.AF_INET):
        answers = await asyncio.get_running_loop().getaddrinfo(host, port, family=family, type=socket.SOCK_STREAM)
        result = []
        for af, socktype, proto, canonname, address in answers:
            if not ipaddress.ip_address(address[0]).is_global:
                raise OSError("Non-public URL destination")
            result.append({"hostname": host, "host": address[0], "port": port,
                           "family": af, "proto": proto, "flags": socket.AI_NUMERICHOST})
        return result

    async def close(self):
        pass


async def public_get(url):
    """Separate session: no Twitch credentials, cookies, proxies, or redirects."""
    public_url(url)
    connector = aiohttp.TCPConnector(resolver=PublicResolver(), use_dns_cache=False)
    async with aiohttp.ClientSession(connector=connector, timeout=aiohttp.ClientTimeout(total=5),
                                     cookie_jar=aiohttp.DummyCookieJar(), trust_env=False) as session:
        async with session.get(url, allow_redirects=False, headers={"User-Agent": "Paimon-TwitchBridge/1.0"}) as response:
            if response.status != 200:
                raise ValueError("Public lookup failed.")
            if response.content_type not in ("text/plain", "application/json", "text/json"):
                raise ValueError("URL fetch expects plain text or JSON.")
            data = bytearray()
            async for chunk in response.content.iter_chunked(4096):
                data.extend(chunk)
                if len(data) > 65536:
                    raise ValueError("Public response is too large.")
            return bytes(data).decode("utf-8", errors="replace")


def weather_description(code):
    if code == 0:
        return "clear skies"
    if code in (1, 2):
        return "partly cloudy"
    if code == 3:
        return "overcast"
    if code in (45, 48):
        return "foggy"
    if code in (51, 53, 55, 56, 57):
        return "drizzle"
    if code in (61, 63, 65, 66, 67, 80, 81, 82):
        return "rain"
    if code in (71, 73, 75, 77, 85, 86):
        return "snow"
    if code in (95, 96, 99):
        return "stormy"
    return "conditions unavailable"


class ExtraVariablesMixin:
    async def _public_text(self, url):
        # Each template has a bounded number of lookups and each read is bounded.
        return await public_get(url)

    async def _weather(self, location):
        cache = getattr(self, "weather_cache", None)
        if cache is None:
            self.weather_cache = cache = {}
        key = location.casefold()
        cached = cache.get(key)
        if cached and time.monotonic() - cached[0] < 300:
            return cached[1]
        city, _, country = location.partition("/")
        search = city.strip() + (", " + country.strip() if country else "")
        tokens = await self.bot.get_shared_api_tokens("openmeteo")
        api_key = tokens.get("api_key", "").strip()
        query = {"name": search, "count": 5, "language": "en", "format": "json"}
        if api_key:
            query["apikey"] = api_key
        prefix = "customer-" if api_key else ""
        body = json.loads(await self._public_text("https://" + prefix + "geocoding-api.open-meteo.com/v1/search?" + urlencode(query)))
        results = body.get("results", [])
        if not results:
            return "Weather location not found"
        place = results[0]
        query = {"latitude": place["latitude"], "longitude": place["longitude"],
                 "current": "temperature_2m,weather_code", "temperature_unit": "celsius", "timezone": "auto"}
        if api_key:
            query["apikey"] = api_key
        body = json.loads(await self._public_text("https://" + prefix + "api.open-meteo.com/v1/forecast?" + urlencode(query)))
        current = body["current"]
        result = f"{place['name']}: {weather_description(current['weather_code'])}, {current['temperature_2m']:g}°C (Open-Meteo)"
        cache[key] = (time.monotonic(), result)
        if len(cache) > 256:
            cache.pop(next(iter(cache)))
        return result

    async def _followage(self, guild_id, twitch_id):
        if not twitch_id:
            return "Link your Twitch account to see follow duration"
        async with self.settings_lock:
            cfg = await self.config.guild_from_id(guild_id).all()
            bid = cfg["broadcaster_id"]
            client_id, auth = await self._role_token(guild_id, {"moderator:read:followers"})
        code, body = await self._request("GET", "https://api.twitch.tv/helix/channels/followers",
            params={"broadcaster_id": bid, "user_id": str(twitch_id)},
            headers={"Client-Id": client_id, "Authorization": "Bearer " + auth["access_token"]})
        if code != 200:
            raise BridgeError("Follow information is unavailable.")
        rows = body.get("data", [])
        if not rows:
            return "Not following this channel"
        started = datetime.fromisoformat(rows[0]["followed_at"].replace("Z", "+00:00"))
        return calendar_duration(started, datetime.now(timezone.utc))

    async def _extra_variables(self, guild_id, template, *, twitch_id=None):
        matches = list(dict.fromkeys(m[0] for m in DYNAMIC.finditer(template)))
        if len(matches) > 8:
            raise ValueError("Use at most eight different extended variables per message.")
        result = {}
        # Parse every expression first so bad syntax cannot trigger partial network work.
        expressions = [(raw, *parse_variable(raw[1:-1])) for raw in matches]
        for raw, name, args in expressions:
            try:
                if name == "countdown":
                    now = datetime.now(timezone.utc)
                    target = countdown_target(args, now=now)
                    value = calendar_duration(now.astimezone(target.tzinfo), target)
                elif name == "time":
                    value = datetime.now(zone(args[0])).strftime("%Y-%m-%d %H:%M:%S %Z")
                elif name == "random":
                    value = str(random.randint(int(args[0]), int(args[1])))
                elif name == "choose":
                    value = random.choice(args)
                elif name == "randomreply":
                    roll = random.randint(1, int(args[-2]))
                    value = next(text for threshold, text in zip(args[::2], args[1::2]) if roll <= int(threshold))
                    value = value.replace("{roll}", str(roll))
                elif name == "urlfetch":
                    value = (await self._public_text(args[0]))[:500]
                elif name == "weather":
                    value = await self._weather(" ".join(args))
                else:
                    value = await self._followage(guild_id, twitch_id)
            except (BridgeError, aiohttp.ClientError, asyncio.TimeoutError, OSError, ValueError, KeyError, TypeError, AttributeError):
                value = {"weather": "Weather unavailable", "urlfetch": "URL fetch unavailable",
                         "followage": "Follow information unavailable"}.get(name, "Variable unavailable")
            result[raw] = " ".join("".join(c for c in str(value) if ord(c) >= 32 or c.isspace()).split())
        return result


def mask_extended(template):
    """Map parameterized expressions to inert format fields for event templates."""
    values = {}
    def replace(match):
        parse_variable(match[1])
        key = "__extended_" + str(len(values))
        values[key] = match[0]
        return "{" + key + "}"
    masked = DYNAMIC.sub(replace, template)
    if len(set(values.values())) > 8:
        raise ValueError("Use at most eight different extended variables per message.")
    return masked, values

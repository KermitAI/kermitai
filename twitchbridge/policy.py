"""Small transport-independent validation and routing rules."""
from collections import OrderedDict
from datetime import datetime, timezone
from urllib.parse import urlsplit
import re


def login_name(value):
    value = value.strip().lower()
    if not re.fullmatch(r"[a-z0-9_]{1,25}", value):
        raise ValueError("Use a Twitch username, not a URL.")
    return value


def reconnect_url(value):
    url = urlsplit(value)
    if (url.scheme != "wss" or url.hostname != "eventsub.wss.twitch.tv"
            or url.port not in (None, 443) or url.username or url.password
            or url.fragment or url.path != "/ws"):
        raise ValueError("Invalid Twitch reconnect destination.")
    return value


class RecentMessages:
    def __init__(self, limit=10000):
        self.limit = limit
        self.items = OrderedDict()

    def accept(self, key):
        if not key or key in self.items:
            return False
        self.items[key] = None
        if len(self.items) > self.limit:
            self.items.popitem(last=False)
        return True


def log_line(event, timestamp):
    # Prevent Twitch content from becoming Discord markdown, mentions or embeds.
    def clean(value):
        value = str(value).replace("\n", " ").replace("\r", " ")
        value = re.sub(r"([\\`*_{}\[\]()<>#+.!|~])", r"\\\1", value)
        return value
    try:
        moment = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        stamp = moment.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    except (ValueError, AttributeError):
        stamp = "time unavailable"
    name = clean(event.get("chatter_user_name", event.get("chatter_user_login", "unknown")))
    text = clean(event.get("message", {}).get("text", ""))
    return f"[{stamp}] {name}: {text}"[:1900]


RESERVED_COMMANDS = {"twitchset", "twitchcommand", "twitchannounce"}


def command_name(value):
    value = value.lower().lstrip("!")
    if not re.fullmatch(r"[a-z0-9_]{1,32}", value) or value in RESERVED_COMMANDS:
        raise ValueError("Use a command name of 1-32 letters, numbers or underscores (without a prefix).")
    return value


def chat_text(value):
    value = " ".join(value.split())
    if not value or len(value) > 500 or any(ord(c) < 32 for c in value):
        raise ValueError("Messages must contain 1-500 characters after whitespace is normalized.")
    return value


def render_response(template, *, user, args, channel):
    # One pass: user-supplied arguments cannot introduce additional substitutions.
    values = {"user": user, "args": args, "channel": channel}
    text = re.sub(r"\{(user|args|channel)\}", lambda match: values[match[1]], template)
    return chat_text(text)


def parse_command(text, prefix):
    if not prefix or not text.startswith(prefix):
        return None
    parts = text[len(prefix):].split(maxsplit=1)
    if not parts:
        return None
    return parts[0].lower(), parts[1] if len(parts) > 1 else ""


def twitch_level(event):
    if event.get("chatter_user_id") and event.get("chatter_user_id") == event.get("broadcaster_user_id"):
        return 2
    return 1 if any(badge.get("set_id") == "moderator" for badge in event.get("badges", [])) else 0


def command_allowed(record, platform, level):
    required = {"everyone": 0, "moderator": 1, "broadcaster": 2}
    return (record.get("platform", "twitch") in (platform, "both")
            and record.get("permission", "everyone") in required
            and level >= required[record.get("permission", "everyone")])

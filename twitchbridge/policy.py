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

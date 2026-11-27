"""Small transport-independent validation and routing rules."""
from collections import OrderedDict
from datetime import datetime, timezone
from urllib.parse import urlsplit
import re
from .variables import DYNAMIC, mask_extended


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


PUBLIC_COMMAND_LIST = {"twitchcommands", "tcommands", "tcmds"}

RESERVED_COMMANDS = PUBLIC_COMMAND_LIST | {"timer", "twitchcountdown","quote", "twitchquote","twitchglobal","twitchset", "twitchcommand", "twitchannounce", "twitchlink", "twitchroles", "twitchshoutout", "link", "so", "shoutout", "todo", "ads", "streak", "twitchtodo", "twitchads", "twitchtimer", "twitchtrigger", "twitchcounter", "twitchfirst", "twitchstreak", "tstream", "title", "game", "category", "tags", "language"}


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


def template_text(value):
    value = " ".join(value.split())
    if not value or len(value) > 4000 or any(ord(c) < 32 for c in value):
        raise ValueError("Message templates must contain 1-4000 characters.")
    mask_extended(value)
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
    return 1 if any(badge.get("set_id") in {"moderator", "lead_moderator"} for badge in event.get("badges", [])) else 0


def command_allowed(record, platform, level, *, is_owner=False):
    if record.get("platform", "twitch") not in (platform, "both"):
        return False
    permission = record.get("permission", "everyone")
    if permission == "owner":
        return bool(is_owner)
    required = {"everyone": 0, "moderator": 1, "broadcaster": 2}
    return permission in required and level >= required[permission]


def twitch_target(value):
    value = value.strip()
    if "://" in value or value.lower().startswith(("twitch.tv/", "www.twitch.tv/")):
        url = urlsplit(value if "://" in value else "https://" + value)
        if (url.scheme not in ("http", "https") or url.hostname not in ("twitch.tv", "www.twitch.tv")
                or url.username or url.password or url.port or url.query or url.fragment):
            raise ValueError("Use a Twitch username or a direct twitch.tv/username URL.")
        value = url.path.strip("/")
    return login_name(value.lstrip("@"))


def shoutout_text(template, identity, channel, game="Unknown game", extended=None):
    values = {"user": identity["display_name"], "url": "https://twitch.tv/" + identity["login"], "channel": channel, "game": game}
    pattern = re.compile(DYNAMIC.pattern + r"|\{(?:user|url|channel|game)\}")
    return chat_text(pattern.sub(lambda m: (extended or {}).get(m[0], values.get(m[0][1:-1], m[0])), template))


def resolve_custom_command(records, name):
    """Resolve an alternate name directly to its canonical command record."""
    if name in records:
        return name, records[name]
    for canonical, record in records.items():
        if name in record.get("aliases", []):
            return canonical, record
    return None, None


def public_command_pages(cfg, global_records=None):
    """Only advertise public custom commands usable on this Twitch channel."""
    prefix = cfg.get("command_prefix", "!")
    local = cfg.get("custom_commands", {})
    effective = {name: record for name, record in (global_records or {}).items()
                 if resolve_custom_command(local, name)[1] is None}
    effective.update(local)
    names = [prefix + name for name, record in sorted(effective.items())
             if record.get("permission") == "everyone" and record.get("platform") in ("twitch", "both")]
    if not names:
        return ["No public custom Twitch commands are configured yet."]
    pages, page = [], "Commands: "
    for name in names:
        separator = "" if page == "Commands: " else ", "
        if len(page) + len(separator) + len(name) > 500:
            pages.append(page)
            page, separator = "Commands: ", ""
        page += separator + name
    pages.append(page)
    return pages

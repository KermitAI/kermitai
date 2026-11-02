"""Static classification of Red command requirements; never executes checks."""
from dataclasses import dataclass

CATEGORIES = (
    "Bot-Owner only", "Guild Owner access", "@Administrators access",
    "@Moderators access", "@everyone access",
)
LEVELS = {"BOT_OWNER": 0, "GUILD_OWNER": 1, "ADMIN": 2, "MOD": 3, "NONE": 4}


@dataclass
class Result:
    category: object
    notes: list


def classify(command):
    """Return declared privilege and qualifications, or None for uncertain access."""
    levels, notes = [], []
    uncertain = False
    nodes = [command, *getattr(command, "parents", ())]
    cog = getattr(command, "cog", None)
    if cog is not None:
        nodes.append(cog)
        # discord.py marks base Cog hooks with a None-valued attribute.
        # Test attribute presence, not truthiness, on the underlying function.
        hook = getattr(cog, "cog_check", None)
        if hook is not None and not hasattr(
            getattr(hook, "__func__", hook), "__cog_special_method__"
        ):
            notes.append("custom cog_check; access needs review")
            uncertain = True
    for node in nodes:
        label = getattr(node, "qualified_name", type(node).__name__)
        requires = getattr(node, "requires", None)
        if requires is None:
            notes.append(f"{label}: no Red permission metadata")
            uncertain = True
        else:
            privilege = getattr(requires, "privilege_level", None)
            name = getattr(privilege, "name", None)
            perms = getattr(requires, "user_perms", None)
            required = [key for key, enabled in perms if enabled] if perms is not None else []
            if name in LEVELS:
                level = LEVELS[name]
                # Red accepts user permissions OR the declared privilege.
                if perms is not None and not required:
                    level = 4
                levels.append(level)
                if required:
                    notes.append(f"{label}: alternatively user permissions: {', '.join(required)}")
            elif perms is not None and not required:
                levels.append(4)
            elif required == ["administrator"]:
                levels.append(2)
            else:
                uncertain = True
                notes.append(f"{label}: permission-only/custom requirement: {', '.join(required) or 'unknown'}")
            if getattr(requires, "checks", ()):
                uncertain = True
                notes.append(f"{label}: custom permission checks")
            # Red exposes no public iterator for permission override rules.
            if (getattr(requires, "_global_rules", {}) or
                    any(getattr(requires, "_guild_rules", {}).values())):
                notes.append(f"{label}: permission overrides configured; actual access may differ")
            bot_perms = getattr(requires, "bot_perms", None)
            if bot_perms is not None:
                needed = [key for key, enabled in bot_perms if enabled]
                if needed:
                    notes.append(f"{label}: bot needs {', '.join(needed)}")
        if getattr(node, "checks", ()):
            uncertain = True
            notes.append(f"{label}: additional command checks")
        if getattr(node, "enabled", True) is False:
            notes.append(f"{label}: disabled")
    if getattr(command, "hidden", False):
        notes.append("hidden from help")
    # An explicit owner restriction remains useful even with additional checks.
    level = min(levels, default=4)
    category = CATEGORIES[level] if not uncertain or level == 0 else None
    return Result(category, list(dict.fromkeys(notes)))


def build_report(commands):
    buckets = {category: [] for category in CATEGORIES}
    review = []
    seen = set()
    for command in sorted(commands, key=lambda cmd: cmd.qualified_name.casefold()):
        if id(command) in seen:
            continue
        seen.add(id(command))
        result = classify(command)
        aliases = getattr(command, "aliases", ())
        row = f"- {command.qualified_name} [{getattr(command, 'cog_name', None) or 'Core'}]"
        if aliases:
            row += f" (aliases: {', '.join(aliases)})"
        if result.notes:
            row += "\n    " + "; ".join(result.notes)
        (review if result.category is None else buckets[result.category]).append(row)
    lines = [
        "COMMAND ACCESS AUDIT", "",
        "Declared Red privilege requirements, including parent commands and cogs.",
        "Admin/mod mean Red's configured roles, not roles matched by name.",
        "Permission alternatives are listed on each command; categories are not exclusive access guarantees.",
        "Overrides, global checks, permission hooks, channel rules and checks inside command bodies can change access.",
        "No commands or checks were executed. This is not a live authorization test.", "",
    ]
    for category, rows in buckets.items():
        lines.extend([f"{category} ({len(rows)})", *(rows or ["(none)"]), ""])
    lines.extend([f"Needs review ({len(review)})", *(review or ["(none)"]), ""])
    return "\n".join(lines), {key: len(rows) for key, rows in buckets.items()}, len(review)

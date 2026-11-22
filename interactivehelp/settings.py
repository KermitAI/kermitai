import re

GROUPS = ("public", "moderator", "administrator", "guild_owner", "bot_owner")
GROUP_LABELS = ("Public", "Moderator", "Administrator", "Guild Owner", "Bot Owner")
DEFAULT = {
    "version": 1,
    "title": "KermitAI Help",
    "intro": "Choose a category to browse commands.",
    "colour": "#21664F",
    "categories": [
        {"id": "relationships", "label": "💍 Relationships", "pinned": True,
         "cogs": [], "commands": ["marry"]},
        {"id": "economy", "label": "🎁 Economy & Gifts", "pinned": True,
         "cogs": ["Economy"], "commands": ["gift", "bank", "payday"]},
        {"id": "games", "label": "🎮 Games", "pinned": True,
         "cogs": ["Incoherent", "Trivia"], "commands": []},
        {"id": "community", "label": "💬 Community", "pinned": True,
         "cogs": ["Alias", "CustomCommands"], "commands": ["help"]},
    ],
    "overrides": {},
}


def string(value, label, limit, *, empty=False):
    if not isinstance(value, str) or len(value) > limit or (not empty and not value.strip()):
        raise ValueError(f"{label} must be text within {limit} characters.")
    return value


def check_keys(value, required, optional=()):
    if not isinstance(value, dict) or not set(required) <= value.keys():
        raise ValueError(f"Required fields: {', '.join(required)}.")
    if value.keys() - set(required) - set(optional):
        raise ValueError("Unrecognized fields in the menu.")


def validate(menu):
    check_keys(menu, DEFAULT, ("staff",))
    if type(menu["version"]) is not int or menu["version"] != 1:
        raise ValueError("Only menu version 1 is supported.")
    string(menu["title"], "Title", 100)
    string(menu["intro"], "Intro", 700, empty=True)
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", string(menu["colour"], "Colour", 7)):
        raise ValueError("Use a hex colour such as #21664F.")
    categories = menu["categories"]
    if not isinstance(categories, list) or len(categories) > 24:
        raise ValueError("Use up to 24 categories. Other Commands is added automatically.")
    ids = {"other"}
    pinned = 0
    for category in categories:
        check_keys(category, ("id", "label", "pinned", "cogs", "commands"), ("description",))
        key = string(category["id"], "Category ID", 40)
        if key in ids or not re.fullmatch(r"[a-z0-9_-]+", key):
            raise ValueError("Category IDs must be unique and use lowercase letters, numbers, _ or -.")
        ids.add(key)
        string(category["label"], "Category label", 80)
        string(category.get("description", ""), "Category description", 100, empty=True)
        if type(category["pinned"]) is not bool:
            raise ValueError("Pinned must be true or false.")
        pinned += category["pinned"]
        for field in ("commands", "cogs"):
            if not isinstance(category[field], list):
                raise ValueError(f"{field} must be a list.")
            for entry in category[field]:
                string(entry, field, 150)
    if pinned > 4:
        raise ValueError("Pin up to four categories.")
    overrides = menu["overrides"]
    if not isinstance(overrides, dict):
        raise ValueError("Overrides must be an object keyed by full command name.")
    for name, entry in overrides.items():
        string(name, "Command", 150)
        check_keys(entry, (), ("group", "hidden", "description", "example", "category"))
        if entry.get("group", "public") not in GROUPS or type(entry.get("hidden", False)) is not bool:
            raise ValueError("Invalid permission group or hidden value.")
        category_id = string(entry.get("category", "other"), "Category ID", 40)
        if category_id not in ids:
            raise ValueError("An override refers to an unknown category.")
        string(entry.get("description", ""), "Description", 800, empty=True)
        string(entry.get("example", ""), "Example", 450, empty=True)
    if "staff" in menu:
        staff = menu["staff"]
        check_keys(staff, (), GROUPS[1:])
        assigned = set()
        for group, names in staff.items():
            if not isinstance(names, list):
                raise ValueError(f"Staff group {group} must be a list of command names.")
            for name in names:
                string(name, "Staff command", 150)
                if name in assigned:
                    raise ValueError("List each staff command only once across all staff groups.")
                assigned.add(name)
    return menu


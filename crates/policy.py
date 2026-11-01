"""Selection and accounting rules, independent of Discord."""
import math
import random


def positive_weight(value):
    return math.isfinite(value) and 0 < value <= 1_000_000


def choose_reward(tiers):
    # Empty tiers never participate, so an opening always awards an item.
    available = [(key, tier) for key, tier in tiers.items() if tier["items"]]
    if not available:
        raise ValueError("No tiers with items are configured yet.")
    key, tier = random.choices(available, weights=[t["weight"] for _, t in available])[0]
    items = list(tier["items"].items())
    name, item = random.choices(items, weights=[i["weight"] for _, i in items])[0]
    return key, name, item["value"]


def award(data, name, value, now):
    inventory = data["inventory"]
    inventory[name] = inventory.get(name, 0) + 1
    data["pulls"] += 1
    data["value"] += value
    data["last_pull"] = now


def ranking(members, current_ids):
    rows = [(uid, data) for uid, data in members.items()
            if uid in current_ids and data["pulls"] > 0]
    return sorted(rows, key=lambda row: (-row[1]["value"], -row[1]["pulls"], row[0]))


def empty_collection():
    return {"inventory": {}, "pulls": 0, "value": 0, "last_pull": 0}


def merge_collections(target, source):
    """Combine earned totals without rerolling or resetting cooldowns."""
    for name, quantity in source["inventory"].items():
        target["inventory"][name] = target["inventory"].get(name, 0) + quantity
    target["pulls"] += source["pulls"]
    target["value"] += source["value"]
    if "last_pulls" in target or "last_pulls" in source:
        target_times, source_times = platform_pull_times(target), platform_pull_times(source)
        target["last_pulls"] = {platform: max(target_times[platform], source_times[platform])
                                for platform in ("discord", "twitch")}
    target["last_pull"] = max(target["last_pull"], source["last_pull"])


def platform_pull_times(data):
    """Legacy pulls have unknown origin; preserve their cooldown on both platforms."""
    return {platform: data.get("last_pulls", {}).get(platform, data["last_pull"])
            for platform in ("discord", "twitch")}

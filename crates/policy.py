"""Selection and accounting rules, independent of Discord."""
import math
import random
import re


def positive_weight(value):
    return math.isfinite(value) and 0 < value <= 1_000_000


def lucky_tier_weights(tiers, bonus=0):
    """Boost rarer populated tiers; commonest unchanged, rarest gets full bonus."""
    weights = {key: tier["weight"] for key, tier in tiers.items() if tier["items"]}
    if not weights or bonus <= 0:
        return weights
    low, high = min(weights.values()), max(weights.values())
    if low == high:
        return weights
    return {key: weight * (1 + bonus / 100 * (high - weight) / (high - low))
            for key, weight in weights.items()}


def item_weights(crate, bonus=0):
    return lucky_tier_weights({name: {"weight": item["weight"], "items": {"reward": True}}
                               for name, item in crate["items"].items()}, bonus)


def resolve_crate(tiers, name=None):
    if name is not None:
        name = name.lower()
        if name not in tiers:
            raise ValueError("Crate not found. Available crates: " + ", ".join(sorted(tiers)))
    elif len(tiers) == 1:
        name = next(iter(tiers))
    elif not tiers:
        raise ValueError("No crates are configured yet.")
    else:
        raise ValueError("Choose a crate: " + ", ".join(sorted(tiers)) + ". Use crate <name> pull.")
    if not tiers[name]["items"]:
        raise ValueError(f"The {name} crate has no items configured yet.")
    return name


def choose_reward(tiers, bonus=0, crate_name=None, details=False):
    # Empty tiers never participate, so an opening always awards an item.
    available = [(key, tier) for key, tier in tiers.items() if tier["items"]]
    if not available:
        raise ValueError("No tiers with items are configured yet.")
    if crate_name is None:
        weights = lucky_tier_weights(tiers, bonus)
        key, tier = random.choices(available, weights=[weights[key] for key, _ in available])[0]
        weights = {name: item["weight"] for name, item in tier["items"].items()}
    else:
        key = resolve_crate(tiers, crate_name)
        tier = tiers[key]
        weights = item_weights(tier, bonus)
    items = list(tier["items"].items())
    name, item = random.choices(items, weights=[weights[name] for name, _ in items])[0]
    result = (key, (None if item.get("empty", False) else name), (0 if item.get("empty", False) else item["value"]))
    return result + (name,) if details else result


def award(data, name, value, now):
    inventory = data["inventory"]
    if name is not None:
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
    for tier, source_stats in source.get("crate_stats", {}).items():
        target_stats = target.setdefault("crate_stats", {}).setdefault(tier, {"pulls": 0, "value": 0})
        target_stats["pulls"] += source_stats["pulls"]
        target_stats["value"] += source_stats["value"]
    # Preserve cooldown eligibility when verified accounts are merged.
    for collection in (target, source):
        collection.setdefault("cooldown_pools", {}).setdefault(
            "shared", dict(platform_pull_times(collection), shared=collection["last_pull"]))
    for pool, timers in source["cooldown_pools"].items():
        destination = target["cooldown_pools"].setdefault(pool, {})
        for platform, timestamp in timers.items():
            destination[platform] = max(destination.get(platform, 0), timestamp)
    if "last_pulls" in target or "last_pulls" in source:
        target_times, source_times = platform_pull_times(target), platform_pull_times(source)
        target["last_pulls"] = {platform: max(target_times[platform], source_times[platform])
                                for platform in ("discord", "twitch")}
    target["last_pull"] = max(target["last_pull"], source["last_pull"])


def platform_pull_times(data):
    """Legacy pulls have unknown origin; preserve their cooldown on both platforms."""
    return {platform: data.get("last_pulls", {}).get(platform, data["last_pull"])
            for platform in ("discord", "twitch")}


DURATION_LIMIT = 31_536_000
DURATION_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}


def parse_duration(text):
    """Parse plain seconds or whole-number duration components, up to 365 days."""
    text = text.strip().lower()
    error = "Use seconds or durations like 1m, 3h, 1d, 2w, or 1h 30m (maximum 365 days). Use 0 for unlimited pulls."
    if not text or len(text) > 100:
        raise ValueError(error)
    if re.fullmatch(r"[0-9]+", text):
        seconds = int(text)
    else:
        seconds = 0
        position = 0
        for match in re.finditer(r"([0-9]+)\s*([smhdw])", text):
            if text[position:match.start()].strip():
                raise ValueError(error)
            seconds += int(match[1]) * DURATION_UNITS[match[2]]
            position = match.end()
        if position == 0 or text[position:].strip():
            raise ValueError(error)
    if seconds > DURATION_LIMIT:
        raise ValueError(error)
    return seconds


def inventory_by_rarity(inventory, tiers):
    """Sort by current tier weight; unknown items last, alphabetical ties.

    Same-name items stack across tiers, so use their lowest configured tier weight.
    Item weights within a tier do not affect this ordering.
    """
    weights = {}
    for tier in tiers.values():
        for name in tier["items"]:
            weights[name] = min(weights.get(name, math.inf), tier["weight"])
    return sorted(inventory.items(), key=lambda row: (
        weights.get(row[0], math.inf), row[0].casefold(), row[0]))

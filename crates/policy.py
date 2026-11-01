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

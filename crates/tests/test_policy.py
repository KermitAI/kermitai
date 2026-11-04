import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("crate_policy", Path(__file__).parents[1] / "policy.py")
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)


class CratePolicyTests(unittest.TestCase):
    def test_empty_catalog_cannot_pull(self):
        for tiers in ({}, {"empty": {"weight": 1, "items": {}}}):
            with self.assertRaises(ValueError):
                policy.choose_reward(tiers)

    def test_two_stage_weights_and_empty_tier_exclusion(self):
        tiers = {"empty": {"weight": 999, "items": {}},
                 "a": {"weight": 3, "items": {"A": {"weight": 2, "value": 10}}},
                 "b": {"weight": 1, "items": {"B": {"weight": 7, "value": 20}}}}
        def choose(population, *, weights):
            calls.append(weights)
            return [population[-1]]
        calls = []
        with patch.object(policy.random, "choices", side_effect=choose):
            self.assertEqual(policy.choose_reward(tiers), ("b", "B", 20))
        self.assertEqual(calls, [[3, 1], [7]])

    def test_inventory_stacks_and_value_is_awarded_at_pull_time(self):
        data = {"inventory": {}, "pulls": 0, "value": 0, "last_pull": 0}
        policy.award(data, "Item", 10, 100)
        policy.award(data, "Item", 30, 200)
        self.assertEqual(data, {"inventory": {"Item": 2}, "pulls": 2, "value": 40, "last_pull": 200})

    def test_ranking_excludes_nonparticipants_and_departed_members(self):
        members = {1: {"pulls": 0, "value": 0}, 2: {"pulls": 1, "value": 0},
                   3: {"pulls": 2, "value": 5}, 4: {"pulls": 1, "value": 5},
                   5: {"pulls": 99, "value": 999}}
        self.assertEqual([uid for uid, _ in policy.ranking(members, {1, 2, 3, 4})], [3, 4, 2])

    def test_invalid_weights(self):
        for weight in (0, -1, float("nan"), float("inf"), 1_000_001):
            self.assertFalse(policy.positive_weight(weight))
        self.assertTrue(policy.positive_weight(0.5))


class InventoryOrderTests(unittest.TestCase):
    def test_tier_weight_order_ties_and_removed_items(self):
        tiers = {
            "common": {"weight": 0.7, "items": {"Bronze": {"weight": 0.001}}},
            "rare": {"weight": 0.001, "items": {"Zenith": {"weight": 100}, "Alpha": {"weight": 1}}},
        }
        inventory = {"Removed": 2, "Bronze": 9, "Zenith": 1, "Alpha": 3}
        self.assertEqual(policy.inventory_by_rarity(inventory, tiers),
                         [("Alpha", 3), ("Zenith", 1), ("Bronze", 9), ("Removed", 2)])
        self.assertEqual(inventory["Bronze"], 9)

    def test_duplicate_names_use_lowest_tier_weight(self):
        tiers = {"common": {"weight": 0.7, "items": {"Shared": {}}},
                 "rare": {"weight": 0.001, "items": {"Shared": {}}},
                 "middle": {"weight": 0.1, "items": {"Other": {}}}}
        self.assertEqual(policy.inventory_by_rarity({"Other": 1, "Shared": 4}, tiers),
                         [("Shared", 4), ("Other", 1)])
        self.assertEqual(policy.inventory_by_rarity({"Z": 1, "A": 2}, {}), [("A", 2), ("Z", 1)])
        self.assertEqual(policy.inventory_by_rarity({}, tiers), [])


class LuckTests(unittest.TestCase):
    def test_bonus_boosts_rarest_and_preserves_base_weights(self):
        tiers = {key: {"weight": weight, "items": {"Item": {"weight": 1, "value": 1}}}
                 for key, weight in (("rare", .001), ("middle", .25), ("common", .7))}
        tiers["empty"] = {"weight": .00001, "items": {}}
        base = policy.lucky_tier_weights(tiers)
        lucky = policy.lucky_tier_weights(tiers, 50)
        self.assertAlmostEqual(lucky["rare"], .0015)
        self.assertEqual(lucky["common"], .7)
        self.assertGreater(lucky["middle"], base["middle"])
        self.assertLess(lucky["middle"], base["middle"] * 1.5)
        self.assertGreater(lucky["rare"] / sum(lucky.values()), base["rare"] / sum(base.values()))
        self.assertEqual(tiers["rare"]["weight"], .001)
        self.assertNotIn("empty", lucky)
        self.assertEqual(policy.lucky_tier_weights(tiers, 0), base)

    def test_selection_uses_boosted_tier_weights_and_original_item_weights(self):
        tiers = {"rare": {"weight": 1, "items": {"A": {"weight": 7, "value": 10}}},
                 "common": {"weight": 9, "items": {"B": {"weight": 2, "value": 1}}}}
        calls = []
        def choose(population, *, weights):
            calls.append(weights)
            return [population[0]]
        with patch.object(policy.random, "choices", side_effect=choose):
            self.assertEqual(policy.choose_reward(tiers, 50), ("rare", "A", 10))
        self.assertEqual(calls, [[1.5, 9], [7]])

    def test_equal_weights_and_single_tier_are_unchanged(self):
        tiers = {name: {"weight": 1, "items": {"Item": {}}} for name in ("a", "b")}
        self.assertEqual(policy.lucky_tier_weights(tiers, 100), {"a": 1, "b": 1})
        self.assertEqual(policy.lucky_tier_weights({"a": tiers["a"]}, 100), {"a": 1})
        self.assertEqual(policy.lucky_tier_weights({}, 100), {})


class NamedCratePolicyTests(unittest.TestCase):
    def setUp(self):
        self.tiers = {
            "knives": {"weight": 1, "items": {"Bronze": {"weight": 3, "value": 10},
                                                   "Diamond": {"weight": 1, "value": 100}}},
            "gems": {"weight": 999, "items": {"Ruby": {"weight": 1, "value": 50}}},
        }

    def test_multiple_crates_require_explicit_selection(self):
        with self.assertRaises(ValueError):
            policy.resolve_crate(self.tiers)
        self.assertEqual(policy.resolve_crate(self.tiers, "KNIVES"), "knives")
        self.assertEqual(policy.resolve_crate({"knives": self.tiers["knives"]}), "knives")
        for tiers, name in (({}, None), (self.tiers, "missing"), ({"empty": {"items": {}}}, None)):
            with self.assertRaises(ValueError):
                policy.resolve_crate(tiers, name)

    def test_selected_crate_does_not_roll_other_crates_and_luck_changes_item_weights(self):
        calls = []
        def pick(population, *, weights):
            calls.append(weights)
            return [population[-1]]
        with patch.object(policy.random, "choices", side_effect=pick):
            result = policy.choose_reward(self.tiers, 50, crate_name="knives", details=True)
        self.assertEqual(result, ("knives", "Diamond", 100, "Diamond"))
        self.assertEqual(calls, [[3, 1.5]])

    def test_empty_reward_preserves_selected_item_key(self):
        self.tiers["gems"]["items"]["Ruby"]["empty"] = True
        self.assertEqual(policy.choose_reward(self.tiers, crate_name="gems", details=True),
                         ("gems", None, 0, "Ruby"))


class DurationTests(unittest.TestCase):
    def test_shorthand_and_plain_seconds(self):
        cases = {"1m": 60, "3h": 10800, "1d": 86400, "2w": 1209600,
                 "45s": 45, "0": 0, "86400": 86400, " 3H ": 10800,
                 "1h30m": 5400, "1h 30m": 5400, "1 w 2d 3h 4m 5s": 788645,
                 "365d": 31536000, "31536000": 31536000}
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(policy.parse_duration(text), expected)

    def test_invalid_or_excessive_durations(self):
        for text in ("", " ", "-1", "-1h", "1.5h", "1mo", "1y", "tomorrow",
                     "1h garbage", "1h -30m", "1h 30", "1h,30m", "366d",
                     "53w", "31536001", "1" * 101):
            with self.subTest(text=text), self.assertRaises(ValueError):
                policy.parse_duration(text)


if __name__ == "__main__":
    unittest.main()

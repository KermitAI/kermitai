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


if __name__ == "__main__":
    unittest.main()

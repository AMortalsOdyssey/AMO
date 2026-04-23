from __future__ import annotations

import unittest
from pathlib import Path

from graph_cleanup.lib import AliasLink, CharacterRecord, CleanupRules, build_cleanup_plan


class GraphCleanupPlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.rules = CleanupRules.load(Path(__file__).resolve().parents[1] / "rules.json")

    def test_low_value_name_detected(self) -> None:
        self.assertTrue(self.rules.is_low_value_name("王师兄"))
        self.assertTrue(self.rules.is_low_value_name("老者"))
        self.assertTrue(self.rules.is_low_value_name("少女"))
        self.assertTrue(self.rules.is_low_value_name("黑色鬼影子"))
        self.assertTrue(self.rules.is_low_value_name("魁梧身影"))
        self.assertTrue(self.rules.is_low_value_name("黑衣少妇"))
        self.assertTrue(self.rules.is_low_value_name("王门主"))
        self.assertTrue(self.rules.is_low_value_name("骅道友"))
        self.assertTrue(self.rules.is_low_value_name("元姓大汉"))
        self.assertTrue(self.rules.is_low_value_name("韩立父母"))
        self.assertTrue(self.rules.is_low_value_name("第二元婴"))
        self.assertFalse(self.rules.is_low_value_name("凌玉灵"))

    def test_pruned_relation_types_detected(self) -> None:
        self.assertTrue(self.rules.should_prune_relation_type("旧识"))
        self.assertTrue(self.rules.should_prune_relation_type("敌对"))
        self.assertFalse(self.rules.should_prune_relation_type("血亲"))

    def test_alias_links_and_manual_map_create_merge_candidates(self) -> None:
        characters = [
            CharacterRecord(id=1, name="凌玉灵", is_major=True, first_chapter=504, relation_count=8),
            CharacterRecord(id=2, name="玉灵", is_major=False, first_chapter=1137, relation_count=2),
            CharacterRecord(id=3, name="天星双圣", is_major=True, first_chapter=389, relation_count=4),
            CharacterRecord(id=4, name="双圣", is_major=False, first_chapter=456, relation_count=1),
        ]
        alias_links = [
            AliasLink(alias_id=4, alias_name="双圣", canonical_id=3, canonical_name="天星双圣", relation_count=1),
        ]
        plan = build_cleanup_plan(characters, alias_links, self.rules)
        merge_pairs = {(item.alias_name, item.canonical_name, item.reason) for item in plan.merges}
        self.assertIn(("双圣", "天星双圣", "manual_alias_map"), merge_pairs)
        self.assertIn(("玉灵", "凌玉灵", "manual_alias_map"), merge_pairs)

    def test_low_value_unmerged_names_become_prunes(self) -> None:
        characters = [
            CharacterRecord(id=1, name="凌玉灵", is_major=True, first_chapter=504, relation_count=8),
            CharacterRecord(id=2, name="王师兄", is_major=False, first_chapter=500, relation_count=3),
            CharacterRecord(id=3, name="老者", is_major=False, first_chapter=5, relation_count=2),
        ]
        plan = build_cleanup_plan(characters, [], self.rules)
        pruned_names = {item.character_name for item in plan.prunes}
        self.assertEqual(pruned_names, {"王师兄", "老者"})

    def test_ambiguous_alias_targets_are_skipped(self) -> None:
        characters = [
            CharacterRecord(id=1, name="少女", is_major=False, first_chapter=100, relation_count=13),
            CharacterRecord(id=2, name="张袖儿", is_major=False, first_chapter=101, relation_count=5),
            CharacterRecord(id=3, name="田琴儿", is_major=False, first_chapter=102, relation_count=4),
        ]
        alias_links = [
            AliasLink(alias_id=1, alias_name="少女", canonical_id=2, canonical_name="张袖儿", relation_count=13),
            AliasLink(alias_id=1, alias_name="少女", canonical_id=3, canonical_name="田琴儿", relation_count=13),
        ]
        plan = build_cleanup_plan(characters, alias_links, self.rules)
        self.assertEqual(len(plan.merges), 0)
        self.assertEqual(plan.skipped_aliases[0]["reason"], "ambiguous_alias_targets")

    def test_low_value_canonical_target_is_not_auto_merged(self) -> None:
        characters = [
            CharacterRecord(id=1, name="二老", is_major=False, first_chapter=100, relation_count=3),
            CharacterRecord(id=2, name="鬼灵门长老", is_major=False, first_chapter=90, relation_count=5),
        ]
        alias_links = [
            AliasLink(alias_id=1, alias_name="二老", canonical_id=2, canonical_name="鬼灵门长老", relation_count=3),
        ]
        plan = build_cleanup_plan(characters, alias_links, self.rules)
        self.assertEqual(len(plan.merges), 0)
        self.assertEqual(plan.skipped_aliases[0]["reason"], "low_value_canonical_target")

    def test_reciprocal_alias_cycle_collapses_to_single_canonical(self) -> None:
        characters = [
            CharacterRecord(id=1, name="马容", is_major=False, first_chapter=10, relation_count=2),
            CharacterRecord(id=2, name="马荣", is_major=False, first_chapter=8, relation_count=5),
        ]
        alias_links = [
            AliasLink(alias_id=1, alias_name="马容", canonical_id=2, canonical_name="马荣", relation_count=2),
            AliasLink(alias_id=2, alias_name="马荣", canonical_id=1, canonical_name="马容", relation_count=5),
        ]
        plan = build_cleanup_plan(characters, alias_links, self.rules)
        self.assertEqual(len(plan.merges), 1)
        self.assertEqual(plan.merges[0].alias_name, "马容")
        self.assertEqual(plan.merges[0].canonical_name, "马荣")
        self.assertEqual(plan.merges[0].reason, "manual_alias_map")


if __name__ == "__main__":
    unittest.main()

import unittest
from types import SimpleNamespace

from app.api.chat import _build_system_prompt, _normalize_text_items


class ChatPromptTests(unittest.TestCase):
    def test_normalize_text_items_flattens_nested_values(self):
        value = [[], ["沉稳", "谨慎"], None, {"extra": ["老成"]}, 3]
        self.assertEqual(_normalize_text_items(value), ["沉稳", "谨慎", "老成", "3"])

    def test_build_system_prompt_tolerates_nested_snapshot_arrays(self):
        snapshot = SimpleNamespace(
            persona_prompt="",
            personality_traits=[[]],
            equipment={},
            techniques=[[]],
            realm_stage="unknown",
            knowledge_cutoff=454,
        )

        prompt = _build_system_prompt("青易居士", snapshot)

        self.assertIn("你正在扮演《凡人修仙传》中的角色「青易居士」", prompt)
        self.assertIn("第 454 章", prompt)


if __name__ == "__main__":
    unittest.main()

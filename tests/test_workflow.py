import unittest
from unittest.mock import patch

from workflow import human_gate


class HumanGateTests(unittest.TestCase):
    def test_whitespace_and_invisible_input_is_treated_as_approval(self):
        with patch("builtins.input", return_value=" \t\u3000\u200b\ufeff "):
            result = human_gate("测试阶段")

        self.assertIsNone(result)

    def test_skip_human_auto_confirms_without_reading_input(self):
        with patch("builtins.input") as input_mock:
            result = human_gate("测试阶段", skip_human=True)

        self.assertIsNone(result)
        input_mock.assert_not_called()

    def test_feedback_message_uses_dynamic_agent_display_name(self):
        with patch("builtins.input", return_value="补充原始需求"), \
                patch("builtins.print") as output:
            result = human_gate(
                "大需求拆分",
                feedback_target="需求拆分agent(codex)",
            )

        self.assertEqual(result, "补充原始需求")
        printed = "\n".join(str(call.args[0]) for call in output.call_args_list if call.args)
        self.assertIn("正在指示 需求拆分agent(codex) 重新调整", printed)
        self.assertNotIn("Claude", printed)


if __name__ == "__main__":
    unittest.main()

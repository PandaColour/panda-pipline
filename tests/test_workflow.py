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


if __name__ == "__main__":
    unittest.main()

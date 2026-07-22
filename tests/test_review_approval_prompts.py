import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROMPTS = {
    ROOT / "break-system-prompt" / "requirement_break_reviewer.md": "拆分方案通过",
    ROOT / "break-system-prompt" / "item_requirements_reviewer.md": "同意方案",
    ROOT / "break-system-prompt" / "item_code_reviewer.md": "任务完成",
    ROOT / "system-prompt" / "requirements_reviewer.md": "同意方案",
    ROOT / "system-prompt" / "code_reviewer.md": "任务完成",
}


class ReviewApprovalPromptTests(unittest.TestCase):
    def test_approval_tokens_are_required_on_the_first_line_within_fifty_characters(self):
        for prompt_file, approval_token in PROMPTS.items():
            content = prompt_file.read_text(encoding="utf-8")
            self.assertIn(approval_token, content, prompt_file.name)
            self.assertIn("第一行", content, prompt_file.name)
            self.assertIn("前 50", content, prompt_file.name)


if __name__ == "__main__":
    unittest.main()

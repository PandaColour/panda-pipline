import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROMPTS = [path for directory in ('system-prompt', 'break-system-prompt')
           for path in (ROOT / directory).glob('*.md')]


class ReviewApprovalPromptTests(unittest.TestCase):
    def test_all_roles_use_status_and_optional_approval_description(self):
        for prompt_file in PROMPTS:
            content = prompt_file.read_text(encoding="utf-8")
            self.assertIn('approval_token 仅为可选补充说明', content, prompt_file.name)
            self.assertIn('不参与流程判定', content, prompt_file.name)
            self.assertNotIn('准确批准令牌', content, prompt_file.name)
            self.assertNotIn('且 `approval_token=', content, prompt_file.name)
            self.assertIn("2048", content, prompt_file.name)
            self.assertIn("outputs", content, prompt_file.name)
            self.assertNotIn("前 50", content, prompt_file.name)


if __name__ == "__main__":
    unittest.main()

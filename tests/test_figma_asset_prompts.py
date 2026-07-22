import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
Figma_ANALYSIS_PROMPTS = [
    ROOT / "break-system-prompt" / "requirement_breaker.md",
    ROOT / "break-system-prompt" / "requirement_break_reviewer.md",
    ROOT / "break-system-prompt" / "item_requirements_analyst.md",
    ROOT / "break-system-prompt" / "item_requirements_reviewer.md",
    ROOT / "system-prompt" / "requirements_analyst.md",
    ROOT / "system-prompt" / "requirements_reviewer.md",
]
CODE_REVIEW_PROMPTS = [
    ROOT / "break-system-prompt" / "item_code_reviewer.md",
    ROOT / "system-prompt" / "code_reviewer.md",
]


class FigmaAssetPromptTests(unittest.TestCase):
    def test_requirement_prompts_require_local_assets_and_usage_mapping(self):
        for prompt_file in Figma_ANALYSIS_PROMPTS:
            content = prompt_file.read_text(encoding="utf-8")
            self.assertIn("figma_assets/", content, prompt_file.name)
            self.assertIn("物料映射表", content, prompt_file.name)

    def test_key_requirement_prompts_require_figma_images_to_be_downloaded_locally(self):
        prompt_files = [
            ROOT / "break-system-prompt" / "requirement_breaker.md",
            ROOT / "break-system-prompt" / "requirement_break_reviewer.md",
            ROOT / "system-prompt" / "requirements_analyst.md",
            ROOT / "system-prompt" / "requirements_reviewer.md",
        ]
        for prompt_file in prompt_files:
            content = prompt_file.read_text(encoding="utf-8")
            self.assertIn("图片物料", content, prompt_file.name)
            self.assertIn("下载到本地", content, prompt_file.name)

    def test_code_review_prompts_require_asset_reuse_review(self):
        for prompt_file in CODE_REVIEW_PROMPTS:
            content = prompt_file.read_text(encoding="utf-8")
            self.assertIn("物料复用", content, prompt_file.name)
            self.assertIn("重复", content, prompt_file.name)

    def test_breakdown_prompts_require_a_complete_execution_index(self):
        for prompt_file in [
            ROOT / "break-system-prompt" / "requirement_breaker.md",
            ROOT / "break-system-prompt" / "requirement_break_reviewer.md",
        ]:
            content = prompt_file.read_text(encoding="utf-8")
            self.assertIn("验收摘要", content, prompt_file.name)
            self.assertIn("顺序", content, prompt_file.name)

    def test_index_normalizer_can_derive_missing_execution_fields_from_requirements(self):
        content = (ROOT / "break-system-prompt" / "index_normalizer.md").read_text(encoding="utf-8")
        self.assertIn("验收标准", content)
        self.assertIn("拓扑", content)
        self.assertIn("待需求分析（阻塞）", content)
        self.assertIn("只能输出", content)


if __name__ == "__main__":
    unittest.main()

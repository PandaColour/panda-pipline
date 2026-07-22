import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

ANALYSIS_PROMPTS = [
    ROOT / "system-prompt" / "requirements_analyst.md",
    ROOT / "break-system-prompt" / "requirement_breaker.md",
    ROOT / "break-system-prompt" / "item_requirements_analyst.md",
]

DEVELOPER_PROMPTS = [
    ROOT / "system-prompt" / "code_developer.md",
    ROOT / "break-system-prompt" / "item_developer.md",
]

REVIEW_PROMPTS = [
    ROOT / "system-prompt" / "requirements_reviewer.md",
    ROOT / "system-prompt" / "code_reviewer.md",
    ROOT / "break-system-prompt" / "requirement_break_reviewer.md",
    ROOT / "break-system-prompt" / "item_requirements_reviewer.md",
    ROOT / "break-system-prompt" / "item_code_reviewer.md",
]

CODE_REVIEW_PROMPTS = [
    ROOT / "system-prompt" / "code_reviewer.md",
    ROOT / "break-system-prompt" / "item_code_reviewer.md",
]


class BackendMaterialPromptContractTests(unittest.TestCase):
    def test_requirement_analysis_prompts_require_material_and_interface_availability_checks(self):
        for prompt_file in ANALYSIS_PROMPTS:
            content = prompt_file.read_text(encoding="utf-8")
            self.assertIn("物料可用性验证", content, prompt_file.name)
            self.assertIn("接口连通性验证", content, prompt_file.name)
            self.assertIn("无法验证", content, prompt_file.name)

    def test_developer_prompts_require_backend_mock_disclosure_and_human_todo(self):
        for prompt_file in DEVELOPER_PROMPTS:
            content = prompt_file.read_text(encoding="utf-8")
            self.assertIn("后端不可用原因", content, prompt_file.name)
            self.assertIn("mock 方法/位置/范围", content, prompt_file.name)
            self.assertIn("TODO：请人类使用者尽快补充后端接口信息并完善代码", content, prompt_file.name)

    def test_review_prompts_allow_disclosed_mocks_but_require_backend_todo(self):
        for prompt_file in REVIEW_PROMPTS:
            content = prompt_file.read_text(encoding="utf-8")
            self.assertIn("真实后端接口", content, prompt_file.name)
            self.assertIn("不得仅因 mock 存在不通过", content, prompt_file.name)
            self.assertIn("缺少后端不可用原因、mock 方法/位置/范围或 TODO", content, prompt_file.name)
            self.assertIn("TODO：请人类使用者尽快补充后端接口信息并完善代码", content, prompt_file.name)

    def test_code_review_prompts_require_dependency_and_reuse_impact_review(self):
        for prompt_file in CODE_REVIEW_PROMPTS:
            content = prompt_file.read_text(encoding="utf-8")
            self.assertIn("结合实际代码", content, prompt_file.name)
            self.assertIn("已有依赖库", content, prompt_file.name)
            self.assertIn("复用已有代码", content, prompt_file.name)
            self.assertIn("对其他功能的影响最小", content, prompt_file.name)


if __name__ == "__main__":
    unittest.main()

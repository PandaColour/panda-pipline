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

MEMORY_WRITER_PROMPTS = [
    ROOT / "system-prompt" / "requirements_analyst.md",
    ROOT / "system-prompt" / "code_developer.md",
    ROOT / "break-system-prompt" / "requirement_breaker.md",
    ROOT / "break-system-prompt" / "item_requirements_analyst.md",
    ROOT / "break-system-prompt" / "item_developer.md",
]

REMOVED_TESTER_PROMPTS = [
    ROOT / "system-prompt" / "code_tester.md",
    ROOT / "break-system-prompt" / "item_tester.md",
]

RUNTIME_FILES = [
    ROOT / "pipeline.py",
    ROOT / "break_pipeline.py",
]


class BackendMaterialPromptContractTests(unittest.TestCase):
    def test_requirement_analysis_prompts_require_material_and_interface_availability_checks(self):
        for prompt_file in ANALYSIS_PROMPTS:
            content = prompt_file.read_text(encoding="utf-8")
            self.assertIn("物料可用性验证", content, prompt_file.name)
            self.assertIn("接口连通性验证", content, prompt_file.name)
            self.assertIn("无法验证", content, prompt_file.name)

    def test_ui_requirement_analysis_prompts_require_figma_reference_screens_and_visual_baseline(self):
        prompt_files = [
            ROOT / "system-prompt" / "requirements_analyst.md",
            ROOT / "break-system-prompt" / "item_requirements_analyst.md",
        ]
        for prompt_file in prompt_files:
            content = prompt_file.read_text(encoding="utf-8")
            self.assertIn("reference_screens", content, prompt_file.name)
            self.assertIn("视觉基准", content, prompt_file.name)
            self.assertIn("图标尺寸", content, prompt_file.name)
            self.assertIn("无法获取参考图", content, prompt_file.name)

    def test_developer_prompts_require_backend_mock_disclosure_and_human_todo(self):
        for prompt_file in DEVELOPER_PROMPTS:
            content = prompt_file.read_text(encoding="utf-8")
            self.assertIn("后端不可用原因", content, prompt_file.name)
            self.assertIn("mock 方法/位置/范围", content, prompt_file.name)
            self.assertIn("TODO：请人类使用者尽快补充后端接口信息并完善代码", content, prompt_file.name)

    def test_developer_prompts_treat_missing_requirement_interface_info_as_existing_code_signal(self):
        for prompt_file in DEVELOPER_PROMPTS:
            content = prompt_file.read_text(encoding="utf-8")
            self.assertIn("需求文档未提到接口信息", content, prompt_file.name)
            self.assertIn("优先检索仓库既有接口封装、服务调用、API 客户端、路由和配置", content, prompt_file.name)
            self.assertIn("不得直接判定为无接口或自行 mock", content, prompt_file.name)

    def test_item_prompts_keep_original_context_and_test_credentials_visible(self):
        prompt_files = [
            ROOT / "break-system-prompt" / "requirement_breaker.md",
            ROOT / "break-system-prompt" / "requirement_break_reviewer.md",
            ROOT / "break-system-prompt" / "item_requirements_analyst.md",
            ROOT / "break-system-prompt" / "item_developer.md",
        ]
        for prompt_file in prompt_files:
            content = prompt_file.read_text(encoding="utf-8")
            self.assertIn("全局上下文", content, prompt_file.name)
            self.assertIn("测试环境、账号、密码", content, prompt_file.name)
            self.assertIn("原始需求", content, prompt_file.name)

    def test_developer_prompts_require_disclosure_for_requirement_gaps(self):
        for prompt_file in DEVELOPER_PROMPTS:
            content = prompt_file.read_text(encoding="utf-8")
            self.assertIn("需求部分内容缺失", content, prompt_file.name)
            self.assertIn("无法完成的需求点", content, prompt_file.name)
            self.assertIn("缺少的信息", content, prompt_file.name)
            self.assertIn("当前临时方案/位置/范围", content, prompt_file.name)
            self.assertIn("TODO：请人类使用者尽快补充缺失需求信息并完善代码", content, prompt_file.name)

    def test_developer_prompts_allow_self_testing(self):
        for prompt_file in DEVELOPER_PROMPTS:
            content = prompt_file.read_text(encoding="utf-8")
            self.assertIn("允许开发 Agent 自测", content, prompt_file.name)
            self.assertIn("自测命令和结果", content, prompt_file.name)
            self.assertNotIn("不编写或修改测试代码", content, prompt_file.name)
            self.assertNotIn("不编写测试代码", content, prompt_file.name)

    def test_review_prompts_allow_disclosed_mocks_but_require_backend_todo(self):
        for prompt_file in REVIEW_PROMPTS:
            content = prompt_file.read_text(encoding="utf-8")
            self.assertIn("真实后端接口", content, prompt_file.name)
            self.assertIn("不得仅因 mock 存在不通过", content, prompt_file.name)
            self.assertIn("缺少后端不可用原因、mock 方法/位置/范围或 TODO", content, prompt_file.name)
            self.assertIn("TODO：请人类使用者尽快补充后端接口信息并完善代码", content, prompt_file.name)

    def test_review_prompts_allow_evidence_based_inference_without_fabrication(self):
        for prompt_file in REVIEW_PROMPTS:
            content = prompt_file.read_text(encoding="utf-8")
            self.assertIn("证据化推断", content, prompt_file.name)
            self.assertIn("推断依据、影响范围、是否仍需人类确认", content, prompt_file.name)
            self.assertIn("不得编造产品规则、接口契约、权限策略或业务口径", content, prompt_file.name)
            self.assertIn("缺少证据时应要求对应分析或开发 Agent 披露缺口、临时方案、影响和 TODO", content, prompt_file.name)

    def test_code_review_prompts_require_dependency_and_reuse_impact_review(self):
        for prompt_file in CODE_REVIEW_PROMPTS:
            content = prompt_file.read_text(encoding="utf-8")
            self.assertIn("结合实际代码", content, prompt_file.name)
            self.assertIn("已有依赖库", content, prompt_file.name)
            self.assertIn("复用已有代码", content, prompt_file.name)
            self.assertIn("对其他功能的影响最小", content, prompt_file.name)
            self.assertIn("不满足上述要求", content, prompt_file.name)
            self.assertIn("要求开发 Agent 修改", content, prompt_file.name)

    def test_code_review_prompts_allow_well_disclosed_requirement_gaps(self):
        for prompt_file in CODE_REVIEW_PROMPTS:
            content = prompt_file.read_text(encoding="utf-8")
            self.assertIn("需求部分内容缺失导致部分需求点无法完成", content, prompt_file.name)
            self.assertIn("不得仅因这些已披露的未完成项不通过", content, prompt_file.name)
            self.assertIn("无法完成的需求点、缺少的信息、当前临时方案/位置/范围、影响和 TODO", content, prompt_file.name)
            self.assertIn("缺少上述披露", content, prompt_file.name)
            self.assertIn("要求开发 Agent 修改", content, prompt_file.name)

    def test_code_review_prompts_take_over_test_report_output(self):
        for prompt_file in CODE_REVIEW_PROMPTS:
            content = prompt_file.read_text(encoding="utf-8")
            self.assertIn("验证审查 Agent", content, prompt_file.name)
            self.assertIn("写入 `test_report.md`", content, prompt_file.name)
            self.assertIn("执行必要测试", content, prompt_file.name)

    def test_ui_code_review_prompts_require_implementation_screenshot_comparison(self):
        prompt_files = [
            ROOT / "system-prompt" / "code_reviewer.md",
            ROOT / "break-system-prompt" / "item_code_reviewer.md",
        ]
        for prompt_file in prompt_files:
            content = prompt_file.read_text(encoding="utf-8")
            self.assertIn("actual_screens", content, prompt_file.name)
            self.assertIn("视觉对比表", content, prompt_file.name)
            self.assertIn("图标尺寸", content, prompt_file.name)
            self.assertIn("静态验证", content, prompt_file.name)
            self.assertIn("环境阻塞", content, prompt_file.name)

    def test_memory_writer_prompts_define_memory_routing(self):
        for prompt_file in MEMORY_WRITER_PROMPTS:
            content = prompt_file.read_text(encoding="utf-8")
            self.assertIn("收到记忆整理指令", content, prompt_file.name)
            self.assertIn("记忆分类路由", content, prompt_file.name)
            self.assertIn("interfaces.md", content, prompt_file.name)
            self.assertIn("business_rules.md", content, prompt_file.name)
            self.assertIn("ui_guidelines.md", content, prompt_file.name)
            self.assertIn("pitfalls.md", content, prompt_file.name)
            self.assertIn("architecture.md", content, prompt_file.name)

    def test_review_prompts_keep_memory_read_only_and_provide_evidence_reports(self):
        for prompt_file in REVIEW_PROMPTS:
            content = prompt_file.read_text(encoding="utf-8")
            self.assertIn("不得直接写入 `memory/`", content, prompt_file.name)
            self.assertIn("审查报告可作为后续记忆整理输入", content, prompt_file.name)

    def test_old_tester_prompt_files_are_removed_from_runtime(self):
        for prompt_file in REMOVED_TESTER_PROMPTS:
            self.assertFalse(prompt_file.exists(), prompt_file.name)

        runtime_content = "\n".join(path.read_text(encoding="utf-8") for path in RUNTIME_FILES)
        self.assertNotIn("code_tester.md", runtime_content)
        self.assertNotIn("item_tester.md", runtime_content)
        self.assertNotIn("代码单元测试", runtime_content)
        self.assertNotIn("小需求测试", runtime_content)


if __name__ == "__main__":
    unittest.main()

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

SHARED_CONTEXT_CONSUMER_PROMPTS = [
    ROOT / "break-system-prompt" / "item_requirements_analyst.md",
    ROOT / "break-system-prompt" / "item_requirements_reviewer.md",
    ROOT / "break-system-prompt" / "item_developer.md",
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

PROMPT_FOCUS_REQUIREMENTS = {
    ROOT / "system-prompt" / "requirements_analyst.md": [
        "事实/推断/待确认",
        "可验证验收",
        "物料与接口可用性",
    ],
    ROOT / "system-prompt" / "requirements_reviewer.md": [
        "需求完整性",
        "证据边界",
        "验收可测试",
    ],
    ROOT / "system-prompt" / "code_developer.md": [
        "既有框架和依赖复用",
        "真实后端优先",
        "自测与交接",
    ],
    ROOT / "system-prompt" / "code_reviewer.md": [
        "实际测试结果",
        "依赖复用",
        "阻断通过条件",
    ],
    ROOT / "break-system-prompt" / "requirement_breaker.md": [
        "可独立交付",
        "架构师职责",
        "架构复用性",
        "系统长期维护",
        "全局上下文",
        "依赖顺序",
    ],
    ROOT / "break-system-prompt" / "requirement_break_reviewer.md": [
        "覆盖范围",
        "全局上下文",
        "拆分方案通过",
    ],
    ROOT / "break-system-prompt" / "item_requirements_analyst.md": [
        "当前小需求",
        "全局上下文",
        "可实现可验证",
    ],
    ROOT / "break-system-prompt" / "item_requirements_reviewer.md": [
        "当前小需求",
        "同意方案",
        "证据边界",
    ],
    ROOT / "break-system-prompt" / "item_developer.md": [
        "当前小需求",
        "既有框架和依赖复用",
        "develop_report.md",
    ],
    ROOT / "break-system-prompt" / "item_code_reviewer.md": [
        "当前小需求",
        "任务完成",
        "阻断通过条件",
    ],
    ROOT / "break-system-prompt" / "index_normalizer.md": [
        "只写 execution_plan.json",
        "路径与依赖校验",
        "禁止编造",
    ],
}


class BackendMaterialPromptContractTests(unittest.TestCase):
    def test_prompt_files_declare_core_focus_points(self):
        for prompt_file, focus_terms in PROMPT_FOCUS_REQUIREMENTS.items():
            content = prompt_file.read_text(encoding="utf-8")
            self.assertIn("## 核心关注点", content, prompt_file.name)
            for focus_term in focus_terms:
                self.assertIn(focus_term, content, prompt_file.name)

    def test_prompt_files_do_not_embed_repeated_memory_directory_tree(self):
        for prompt_file in PROMPT_FOCUS_REQUIREMENTS:
            content = prompt_file.read_text(encoding="utf-8")
            self.assertNotIn("├──", content, prompt_file.name)
            self.assertNotIn("memory_index.md      #", content, prompt_file.name)

    def test_breakdown_prompts_require_batch_shared_context_file(self):
        writer = (ROOT / "break-system-prompt" / "requirement_breaker.md").read_text(encoding="utf-8")
        self.assertIn("requirements/shared_context.md", writer)
        self.assertIn("本批次临时公共信息", writer)
        self.assertIn("planned/unverified", writer)
        self.assertIn("不得写入 `memory/`", writer)

        reviewer = (ROOT / "break-system-prompt" / "requirement_break_reviewer.md").read_text(encoding="utf-8")
        self.assertIn("requirements/shared_context.md", reviewer)
        self.assertIn("本批次临时公共信息", reviewer)
        self.assertIn("planned/unverified", reviewer)
        self.assertIn("不得通过", reviewer)

    def test_breakdown_resource_blocker_requires_original_url_in_human_gate_summary(self):
        writer = (ROOT / "break-system-prompt" / "requirement_breaker.md").read_text(encoding="utf-8")

        self.assertIn("原始完整 URL", writer)
        self.assertIn("`summary` 必须包含同一个原始完整 URL", writer)
        self.assertIn("不得只填写文档名称", writer)

    def test_item_prompts_require_reading_batch_shared_context(self):
        for prompt_file in SHARED_CONTEXT_CONSUMER_PROMPTS:
            content = prompt_file.read_text(encoding="utf-8")
            self.assertIn("requirements/shared_context.md", content, prompt_file.name)
            self.assertIn("本批次临时公共信息", content, prompt_file.name)
            self.assertIn("planned/unverified", content, prompt_file.name)

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

    def test_developer_prompts_require_framework_dependency_scan_before_implementation(self):
        for prompt_file in DEVELOPER_PROMPTS:
            content = prompt_file.read_text(encoding="utf-8")
            self.assertIn("开发前必须先扫描当前代码的框架、依赖包、已有组件、工具函数、服务封装、API 客户端、状态管理、路由和测试工具", content, prompt_file.name)
            self.assertIn("能用项目既有框架、依赖包或已有封装实现的，必须优先复用，不要自己再写一套", content, prompt_file.name)
            self.assertIn("扫描范围、复用结论、未复用原因", content, prompt_file.name)

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

    def test_developer_prompts_require_minimum_smoke_tests_and_layered_fallback(self):
        for prompt_file in DEVELOPER_PROMPTS:
            content = prompt_file.read_text(encoding="utf-8")
            self.assertIn("最小冒烟测试", content, prompt_file.name)
            self.assertIn("不得仅以源码对齐、编译通过或脚本验证替代运行验证", content, prompt_file.name)
            self.assertIn("构建、安装、启动", content, prompt_file.name)
            self.assertIn("mock/stub", content, prompt_file.name)
            self.assertIn("不得将 mock 冒烟结果描述为真实端到端验收", content, prompt_file.name)
            self.assertIn("IDE Run `app`", content, prompt_file.name)

    def test_review_prompts_allow_disclosed_mocks_but_require_backend_todo(self):
        for prompt_file in REVIEW_PROMPTS:
            content = prompt_file.read_text(encoding="utf-8")
            self.assertIn("真实后端接口", content, prompt_file.name)
            self.assertIn("不得仅因 mock 存在不通过", content, prompt_file.name)
            self.assertIn("缺少后端不可用原因、mock 方法/位置/范围或 TODO", content, prompt_file.name)
            self.assertIn("TODO：请人类使用者尽快补充后端接口信息并完善代码", content, prompt_file.name)

    def test_code_review_prompts_require_mock_network_tests_when_credentials_or_network_block_real_validation(self):
        for prompt_file in CODE_REVIEW_PROMPTS:
            content = prompt_file.read_text(encoding="utf-8")
            self.assertIn("测试账号", content, prompt_file.name)
            self.assertIn("网络环境", content, prompt_file.name)
            self.assertIn("mock 网络请求", content, prompt_file.name)
            self.assertIn("开发测试验证", content, prompt_file.name)
            self.assertIn("不得通过", content, prompt_file.name)

    def test_code_review_prompts_block_missing_minimum_smoke_tests(self):
        for prompt_file in CODE_REVIEW_PROMPTS:
            content = prompt_file.read_text(encoding="utf-8")
            self.assertIn("最小冒烟测试审查", content, prompt_file.name)
            self.assertIn("仅有源码分析、编译通过、脚本验证", content, prompt_file.name)
            self.assertIn("账号、权限、网络或后端不可用不是跳过冒烟测试的理由", content, prompt_file.name)
            self.assertIn("分层冒烟测试", content, prompt_file.name)
            self.assertIn("不得通过", content, prompt_file.name)
            self.assertIn("IDE Run `app`", content, prompt_file.name)

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

    def test_code_review_prompts_block_missing_framework_dependency_reuse_scan(self):
        for prompt_file in CODE_REVIEW_PROMPTS:
            content = prompt_file.read_text(encoding="utf-8")
            self.assertIn("重点检查 developer 是否在开发前扫描当前代码的框架、依赖包和已有封装", content, prompt_file.name)
            self.assertIn("能用项目既有框架、依赖包或已有代码实现", content, prompt_file.name)
            self.assertIn("重复造轮子", content, prompt_file.name)
            self.assertIn("不得通过", content, prompt_file.name)

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

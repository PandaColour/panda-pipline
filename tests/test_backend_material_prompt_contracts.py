import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

ITEM_ANALYST_PROMPT = ROOT / "break-system-prompt" / "item_requirements_analyst.md"
ITEM_REQUIREMENTS_REVIEWER_PROMPT = ROOT / "break-system-prompt" / "item_requirements_reviewer.md"
ITEM_DEVELOPER_PROMPT = ROOT / "break-system-prompt" / "item_developer.md"
ITEM_CODE_REVIEWER_PROMPT = ROOT / "break-system-prompt" / "item_code_reviewer.md"
ITEM_PROMPTS = [
    ITEM_ANALYST_PROMPT,
    ITEM_REQUIREMENTS_REVIEWER_PROMPT,
    ITEM_DEVELOPER_PROMPT,
    ITEM_CODE_REVIEWER_PROMPT,
]

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
    def test_primary_analysis_prompts_use_existing_codegraph_index_before_text_search(self):
        prompt_files = [
            ROOT / "break-system-prompt" / "requirement_breaker.md",
            ROOT / "system-prompt" / "requirements_analyst.md",
        ]
        for prompt_file in prompt_files:
            content = prompt_file.read_text(encoding="utf-8")
            self.assertIn(".codegraph/", content, prompt_file.name)
            self.assertIn('codegraph explore "<问题、符号或文件>"', content, prompt_file.name)
            self.assertIn("优先于 `rg`", content, prompt_file.name)
            self.assertIn("不得自行安装或初始化 CodeGraph", content, prompt_file.name)
            self.assertIn("失败时回退", content, prompt_file.name)

    def test_item_prompts_define_acceptance_criteria_as_closed_delivery_boundary(self):
        for prompt_file in ITEM_PROMPTS:
            content = prompt_file.read_text(encoding="utf-8")
            self.assertIn("封闭验收边界", content, prompt_file.name)
            self.assertIn("不得新增隐含验收条件", content, prompt_file.name)

    def test_break_item_validation_is_selected_by_acceptance_type(self):
        analyst = ITEM_ANALYST_PROMPT.read_text(encoding="utf-8")
        developer = ITEM_DEVELOPER_PROMPT.read_text(encoding="utf-8")
        reviewer = ITEM_CODE_REVIEWER_PROMPT.read_text(encoding="utf-8")
        for content in (analyst, developer, reviewer):
            self.assertIn("纯逻辑、状态、数据转换", content)
            self.assertIn("UI 展示、点击、跳转", content)
            self.assertIn("阶段性集成", content)
        self.assertIn("不得机械要求安装、启动或设备截图", developer)
        self.assertIn("不得因缺少设备冒烟而拒绝通过", reviewer)

    def test_developer_prompt_requires_minimum_sufficient_implementation(self):
        content = ITEM_DEVELOPER_PROMPT.read_text(encoding="utf-8")
        self.assertIn("最小充分实现", content)
        self.assertIn("禁止为理论风险扩展", content)
        self.assertIn("CAS、Mutex、版本系统", content)

    def test_code_reviewer_prompt_requires_convergent_re_review(self):
        content = ITEM_CODE_REVIEWER_PROMPT.read_text(encoding="utf-8")
        self.assertIn("首轮一次性", content)
        self.assertIn("稳定 issue ID", content)
        self.assertIn("修复直接引入的回归", content)
        self.assertIn("不得新增与原 issue 无关的阻断项", content)

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

    def test_breakdown_prompts_require_per_target_delivery_levels(self):
        prompts = [
            ROOT / "break-system-prompt" / "requirement_breaker.md",
            ROOT / "break-system-prompt" / "requirement_break_reviewer.md",
        ]
        for prompt_file in prompts:
            content = prompt_file.read_text(encoding="utf-8")
            for value in (
                "android", "ios", "java-backend", "logic", "buildable", "runnable", "deployable",
            ):
                self.assertIn(value, content, prompt_file.name)
            self.assertIn("交付目标与级别", content, prompt_file.name)
            self.assertIn("逐目标", content, prompt_file.name)
            self.assertIn("基础工程", content, prompt_file.name)

        breaker = prompts[0].read_text(encoding="utf-8")
        self.assertIn("R-001", breaker)
        self.assertIn("android: deployable", breaker)

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

    def test_breakdown_prompts_do_not_block_whole_requirement_for_unavailable_external_service(self):
        breaker = (ROOT / "break-system-prompt" / "requirement_breaker.md").read_text(encoding="utf-8")
        self.assertIn("外部服务不可用不得阻塞整个需求", breaker)
        self.assertIn("Mock/Stub/Fake", breaker)
        self.assertIn("独立延期/门禁需求", breaker)
        self.assertIn("不得猜测协议或安全策略", breaker)

    def test_item_requirement_prompts_allow_mock_when_development_environment_is_blocked(self):
        prompt_files = [
            ROOT / "break-system-prompt" / "item_requirements_analyst.md",
            ROOT / "break-system-prompt" / "item_requirements_reviewer.md",
        ]
        for prompt_file in prompt_files:
            content = prompt_file.read_text(encoding="utf-8")
            self.assertIn("开发环境阻塞不得作为整项需求门禁", content, prompt_file.name)
            self.assertIn("后端服务异常", content, prompt_file.name)
            self.assertIn("VPN", content, prompt_file.name)
            self.assertIn("Mock/Stub/Fake", content, prompt_file.name)
            self.assertIn("真实联调未验证", content, prompt_file.name)

        reviewer = prompt_files[1].read_text(encoding="utf-8")
        self.assertIn("不得仅因缺少真实端到端验证而不通过", reviewer)
        self.assertIn("应输出 `approved`", reviewer)
        self.assertNotIn("status=requirement_change", reviewer)

    def test_item_requirement_prompts_define_platform_delivery_gate_details(self):
        analyst = (ROOT / "break-system-prompt" / "item_requirements_analyst.md").read_text(
            encoding="utf-8"
        )
        reviewer = (ROOT / "break-system-prompt" / "item_requirements_reviewer.md").read_text(
            encoding="utf-8"
        )

        for content in (analyst, reviewer):
            for value in (
                "android", "ios", "java-backend", "logic", "buildable", "runnable", "deployable",
            ):
                self.assertIn(value, content)
            self.assertIn("交付门禁明细", content)
            self.assertIn("不得降级", content)
            self.assertIn("compileKotlin", content)
            self.assertIn("compileJava", content)

        for column in (
            "测试命令", "构建命令", "制品路径", "启动/健康验证", "环境/签名/配置验证",
        ):
            self.assertIn(column, analyst)
        self.assertIn("扫描仓库", analyst)
        self.assertIn("低于 `deployable`", reviewer)

    def test_item_requirement_prompts_allow_documented_conservative_product_decisions(self):
        prompt_files = [
            ROOT / "break-system-prompt" / "item_requirements_analyst.md",
            ROOT / "break-system-prompt" / "item_requirements_reviewer.md",
        ]
        for prompt_file in prompt_files:
            content = prompt_file.read_text(encoding="utf-8")
            self.assertIn("Agent 保守决策", content, prompt_file.name)
            self.assertIn("明确的“暂不开发”优先于“开发完整版”", content, prompt_file.name)
            self.assertIn("保持既有线上行为", content, prompt_file.name)
            self.assertIn("新入口默认隐藏", content, prompt_file.name)
            self.assertIn("资金、安全、隐私或不可逆操作必须 fail-closed", content, prompt_file.name)
            self.assertIn("Feature Flag", content, prompt_file.name)
            self.assertIn("恢复条件", content, prompt_file.name)

        reviewer = prompt_files[1].read_text(encoding="utf-8")
        self.assertIn("不得仅因缺少产品负责人逐项签署而不通过", reviewer)
        self.assertIn("应输出 `approved`", reviewer)

    def test_item_delivery_prompts_implement_and_approve_conservative_product_decisions(self):
        developer_file = ROOT / "break-system-prompt" / "item_developer.md"
        reviewer_file = ROOT / "break-system-prompt" / "item_code_reviewer.md"
        developer = developer_file.read_text(encoding="utf-8")
        reviewer = reviewer_file.read_text(encoding="utf-8")

        for prompt_file, content in ((developer_file, developer), (reviewer_file, reviewer)):
            self.assertIn("Agent 保守决策", content, prompt_file.name)
            self.assertIn("默认排除", content, prompt_file.name)
            self.assertIn("新入口默认隐藏", content, prompt_file.name)
            self.assertIn("Feature Flag", content, prompt_file.name)
            self.assertIn("零真实副作用", content, prompt_file.name)
            self.assertIn("保持既有行为", content, prompt_file.name)

        self.assertIn("Agent 保守决策是当前可执行范围", developer)
        self.assertIn(
            "不得修改 `user_requirements.md`、`requirements_analysis.md`、`requirement_review.md`、"
            "`requirements/shared_context.md`、`requirements/index.md` 或 `requirements/execution_plan.json`",
            developer,
        )
        self.assertIn("没有新增业务实现也可以是正确交付", developer)
        self.assertIn("Agent 保守决策执行表", developer)

        self.assertIn("默认排除也是有效实现", reviewer)
        self.assertIn("不得仅因缺少产品负责人逐项签署而不通过", reviewer)
        self.assertIn("不得要求 Developer 修改需求文档", reviewer)
        self.assertIn("不应返回 `requirement_change`", reviewer)
        self.assertIn("默认排除且不交付 UI 时，不要求 Figma 视觉对比或真实业务 E2E", reviewer)
        self.assertIn("应输出 `approved`", reviewer)

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

    def test_generic_developer_prompt_keeps_minimum_smoke_test(self):
        content = (ROOT / "system-prompt" / "code_developer.md").read_text(encoding="utf-8")
        self.assertIn("最小冒烟测试", content)
        self.assertIn("不得仅以源码对齐、编译通过或脚本验证替代运行验证", content)
        self.assertIn("构建、安装、启动", content)
        self.assertIn("mock/stub", content)
        self.assertIn("不得将 mock 冒烟结果描述为真实端到端验收", content)
        self.assertIn("IDE Run `app`", content)

    def test_break_developer_prompt_uses_conditional_runtime_validation(self):
        content = ITEM_DEVELOPER_PROMPT.read_text(encoding="utf-8")
        self.assertIn("按 AC 类型选择最小验证", content)
        self.assertIn("定向单元测试", content)
        self.assertIn("不得机械要求安装、启动或设备截图", content)
        self.assertIn("完整 Android/iOS 设备回归集中在阶段性集成需求", content)
        self.assertIn("不得将 mock 结果描述为真实端到端验收", content)

    def test_android_smoke_prompts_require_adb_hard_timeout(self):
        developer = (ROOT / "break-system-prompt" / "item_developer.md").read_text(encoding="utf-8")
        reviewer = (ROOT / "break-system-prompt" / "item_code_reviewer.md").read_text(encoding="utf-8")
        self.assertIn("开发 Agent 负责启停", developer)
        self.assertIn("subprocess.run", developer)
        self.assertIn("timeout=30", developer)
        self.assertIn("waiting for device", developer)
        self.assertIn("接手启停设备", reviewer)
        self.assertNotIn("adb_safe.py", developer)
        self.assertNotIn("adb_safe.py", reviewer)

    def test_review_prompts_allow_disclosed_mocks_but_require_backend_todo(self):
        for prompt_file in REVIEW_PROMPTS:
            content = prompt_file.read_text(encoding="utf-8")
            self.assertIn("真实后端接口", content, prompt_file.name)
            self.assertIn("不得仅因 mock 存在不通过", content, prompt_file.name)
            self.assertIn("缺少后端不可用原因、mock 方法/位置/范围或 TODO", content, prompt_file.name)
            self.assertIn("TODO：请人类使用者尽快补充后端接口信息并完善代码", content, prompt_file.name)

    def test_generic_code_review_requires_mock_network_tests_for_external_blockers(self):
        content = (ROOT / "system-prompt" / "code_reviewer.md").read_text(encoding="utf-8")
        self.assertIn("测试账号", content)
        self.assertIn("网络环境", content)
        self.assertIn("mock 网络请求", content)
        self.assertIn("开发测试验证", content)
        self.assertIn("不得通过", content)

    def test_break_code_review_limits_mock_validation_to_current_acceptance_boundary(self):
        content = ITEM_CODE_REVIEWER_PROMPT.read_text(encoding="utf-8")
        self.assertIn("当前 AC 可控边界", content)
        self.assertIn("不得因外部条件不可用要求重复返工", content)
        self.assertIn("不得循环要求 developer 恢复外部环境", content)

    def test_item_code_reviewer_routes_external_blockers_without_developer_rework_loop(self):
        prompt_file = ROOT / "break-system-prompt" / "item_code_reviewer.md"
        content = prompt_file.read_text(encoding="utf-8")

        self.assertIn("外部服务不可用不得阻塞代码审查通过", content)
        self.assertIn("不得把取得外部签收、恢复服务或提供业务审批令牌作为 developer 的修改项", content)
        self.assertIn("无法由代码、测试或报告修改解决", content)
        self.assertIn("status=requirement_change", content)
        self.assertIn("不得重复返回 changes_requested", content)
        self.assertIn("不得猜测协议或安全策略", content)

    def test_item_code_reviewer_routes_unverifiable_required_ac_to_requirement_change(self):
        content = ITEM_CODE_REVIEWER_PROMPT.read_text(encoding="utf-8")

        self.assertNotIn("blocked", content)
        self.assertIn("外部条件导致“必须”AC无法达到 required_level", content)
        self.assertIn("统一返回 `requirement_change`", content)
        self.assertIn("不得输出 `approved` 或 `changes_requested`", content)

    def test_item_delivery_prompts_execute_and_review_per_target_delivery_gates(self):
        developer = (ROOT / "break-system-prompt" / "item_developer.md").read_text(
            encoding="utf-8"
        )
        reviewer = ITEM_CODE_REVIEWER_PROMPT.read_text(encoding="utf-8")

        for content in (developer, reviewer):
            for value in (
                "android", "ios", "java-backend", "logic", "buildable", "runnable", "deployable",
            ):
                self.assertIn(value, content)
            self.assertIn("逐目标", content)
            self.assertIn("完整构建", content)
            self.assertIn("compileKotlin", content)
            self.assertIn("compileJava", content)
            self.assertIn("上传应用商店", content)
            self.assertIn("发布生产", content)

        self.assertIn("develop_report.md", developer)
        self.assertIn("实际执行", developer)
        self.assertIn("test_report.md", reviewer)
        self.assertIn("较低级别证据", reviewer)
        self.assertIn("统一返回 `requirement_change`", reviewer)
        self.assertNotIn("blocked", reviewer)

    def test_generic_code_review_prompt_blocks_missing_minimum_smoke_tests(self):
        content = (ROOT / "system-prompt" / "code_reviewer.md").read_text(encoding="utf-8")
        self.assertIn("最小冒烟测试审查", content)
        self.assertIn("仅有源码分析、编译通过、脚本验证", content)
        self.assertIn("账号、权限、网络或后端不可用不是跳过冒烟测试的理由", content)
        self.assertIn("分层冒烟测试", content)
        self.assertIn("不得通过", content)
        self.assertIn("IDE Run `app`", content)

    def test_break_code_review_prompt_uses_conditional_runtime_validation(self):
        content = ITEM_CODE_REVIEWER_PROMPT.read_text(encoding="utf-8")
        self.assertIn("条件式运行验证审查", content)
        self.assertIn("不得因为项目是移动端就机械要求", content)
        self.assertIn("不得因缺少设备冒烟而拒绝通过", content)
        self.assertIn("阶段性集成", content)

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

    def test_generic_code_review_blocks_missing_framework_dependency_reuse_scan(self):
        content = (ROOT / "system-prompt" / "code_reviewer.md").read_text(encoding="utf-8")
        self.assertIn("重点检查 developer 是否在开发前扫描当前代码的框架、依赖包和已有封装", content)
        self.assertIn("能用项目既有框架、依赖包或已有代码实现", content)
        self.assertIn("重复造轮子", content)
        self.assertIn("不得通过", content)

    def test_break_code_review_only_blocks_reuse_defects_with_delivery_impact(self):
        content = ITEM_CODE_REVIEWER_PROMPT.read_text(encoding="utf-8")
        self.assertIn("重复造轮子只有已造成", content)
        self.assertIn("对应 AC 或失败证据", content)
        self.assertIn("否则作为非阻断建议", content)

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

    def test_ui_code_review_prompts_require_relevant_implementation_screenshot_comparison(self):
        generic = (ROOT / "system-prompt" / "code_reviewer.md").read_text(encoding="utf-8")
        item = ITEM_CODE_REVIEWER_PROMPT.read_text(encoding="utf-8")
        for content in (generic, item):
            self.assertIn("actual_screens", content)
            self.assertIn("视觉对比表", content)
            self.assertIn("静态验证", content)
            self.assertIn("环境阻塞", content)
        self.assertIn("图标尺寸", generic)
        self.assertIn("只对当前“必须”UI AC", item)
        self.assertIn("不得扩张到 AC 未提及", item)

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

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
DEVELOPER_PROMPTS = [
    ROOT / "break-system-prompt" / "item_developer.md",
    ROOT / "system-prompt" / "code_developer.md",
]
REVIEWER_PROMPTS = CODE_REVIEW_PROMPTS
BREAKDOWN_PROMPTS = [
    ROOT / "break-system-prompt" / "requirement_breaker.md",
    ROOT / "break-system-prompt" / "requirement_break_reviewer.md",
]
ITEM_ANALYST_PROMPTS = [
    ROOT / "break-system-prompt" / "item_requirements_analyst.md",
    ROOT / "system-prompt" / "requirements_analyst.md",
]
ITEM_REQUIREMENTS_REVIEWER_PROMPTS = [
    ROOT / "break-system-prompt" / "item_requirements_reviewer.md",
    ROOT / "system-prompt" / "requirements_reviewer.md",
]


class FigmaAssetPromptTests(unittest.TestCase):
    def test_all_ui_roles_share_scoped_selection_and_motion_contract(self):
        for path in Figma_ANALYSIS_PROMPTS + DEVELOPER_PROMPTS + REVIEWER_PROMPTS:
            content = path.read_text(encoding="utf-8")
            for term in ("不是下载清单", "exportSettings", "selection_evidence",
                         "required=false", "decision=pending", "animation_evidence", "schema_version: 2"):
                self.assertIn(term, content, path.name)
            self.assertNotIn("同类全库检查", content, path.name)

    def test_ui_roles_cover_both_platforms_and_complete_state_manifest(self):
        ui_roles = ITEM_ANALYST_PROMPTS + DEVELOPER_PROMPTS + REVIEWER_PROMPTS
        for prompt_file in ui_roles:
            content = prompt_file.read_text(encoding="utf-8")
            self.assertIn("Android", content, prompt_file.name)
            self.assertIn("iOS", content, prompt_file.name)
            self.assertIn("页面/状态矩阵", content, prompt_file.name)
            self.assertIn("每个页面/状态", content, prompt_file.name)

    def test_ui_roles_require_evidence_and_tolerance_contract(self):
        required_terms = [
            "UI fidelity manifest",
            "business_canvas",
            "platform_owned",
            "external_asset/content",
            "P0",
            "P1",
            "P2",
            "失败节点",
        ]
        for prompt_file in ITEM_ANALYST_PROMPTS + DEVELOPER_PROMPTS + REVIEWER_PROMPTS:
            content = prompt_file.read_text(encoding="utf-8")
            for term in required_terms:
                self.assertIn(term, content, prompt_file.name)

        for prompt_file in DEVELOPER_PROMPTS + REVIEWER_PROMPTS:
            content = prompt_file.read_text(encoding="utf-8")
            self.assertIn("当前构建截图", content, prompt_file.name)

    def test_developers_and_reviewers_reject_partial_visual_evidence(self):
        for prompt_file in DEVELOPER_PROMPTS + REVIEWER_PROMPTS:
            content = prompt_file.read_text(encoding="utf-8")
            self.assertIn("不得仅抽样", content, prompt_file.name)
            self.assertIn("声明值", content, prompt_file.name)
            self.assertIn("截图证据", content, prompt_file.name)

    def test_breakdown_prompts_preserve_platform_state_and_node_metadata(self):
        for prompt_file in BREAKDOWN_PROMPTS:
            content = prompt_file.read_text(encoding="utf-8")
            for term in ("平台列表", "状态列表", "Figma node-id", "容差策略"):
                self.assertIn(term, content, prompt_file.name)

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

    def test_ui_prompts_make_get_figma_node_remote_first(self):
        prompt_files = Figma_ANALYSIS_PROMPTS + DEVELOPER_PROMPTS + REVIEWER_PROMPTS
        for prompt_file in prompt_files:
            content = prompt_file.read_text(encoding="utf-8")
            self.assertIn("get_figma_node", content, prompt_file.name)
            self.assertIn("以远程 Figma 为准", content, prompt_file.name)

    def test_developer_prompts_require_remote_read_evidence_and_bounded_fallback(self):
        for prompt_file in DEVELOPER_PROMPTS:
            content = prompt_file.read_text(encoding="utf-8")
            self.assertIn("Figma 远程读取记录", content, prompt_file.name)
            self.assertIn("不得静默降级", content, prompt_file.name)
            self.assertIn("仅对失败节点降级", content, prompt_file.name)

    def test_reviewer_prompts_reject_missing_remote_read_evidence(self):
        for prompt_file in REVIEWER_PROMPTS:
            content = prompt_file.read_text(encoding="utf-8")
            self.assertIn("缺少远程读取证据", content, prompt_file.name)
            self.assertIn("changes_requested", content, prompt_file.name)

    def test_prompts_do_not_make_remote_figma_optional_or_downstream_local_only(self):
        forbidden = [
            "可按需只读相关 Figma/Sigma node-id 复核",
            "拆分阶段是流水线中唯一能访问 Figma 的阶段",
            "后续所有 Agent 只能读取本地文件",
        ]
        prompt_files = Figma_ANALYSIS_PROMPTS + DEVELOPER_PROMPTS + REVIEWER_PROMPTS
        for prompt_file in prompt_files:
            content = prompt_file.read_text(encoding="utf-8")
            for phrase in forbidden:
                self.assertNotIn(phrase, content, prompt_file.name)

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
        self.assertIn("阻断（待外部契约）", content)
        self.assertIn("归一为旧的 `阻塞`", content)
        self.assertIn("`外部阻塞` 必须原样保留", content)

    def test_breakdown_prompts_require_manifest_agent_run_audit_and_full_mcp_coverage(self):
        for prompt_file in BREAKDOWN_PROMPTS:
            content = prompt_file.read_text(encoding="utf-8")
            self.assertIn("asset_manifest.json", content, prompt_file.name)
            self.assertIn("figma_asset_audit.py", content, prompt_file.name)
            self.assertIn("全部 FRAME", content, prompt_file.name)
            self.assertIn("不得抽样", content, prompt_file.name)
        breaker = BREAKDOWN_PROMPTS[0].read_text(encoding="utf-8")
        self.assertIn("资源访问阻塞", breaker)
        self.assertIn("本地物料不完整", breaker)
        reviewer = BREAKDOWN_PROMPTS[1].read_text(encoding="utf-8")
        self.assertIn("独立运行", reviewer)
        self.assertIn("当前需求范围内同类检查", reviewer)
        self.assertIn("全程只读", reviewer)
        self.assertIn("changes_requested", reviewer)
        self.assertIn("Requirement Breaker", reviewer)

    def test_requirement_analysts_own_only_current_material_and_run_scoped_audit(self):
        for prompt_file in ITEM_ANALYST_PROMPTS:
            content = prompt_file.read_text(encoding="utf-8")
            self.assertIn("asset_manifest.json", content, prompt_file.name)
            self.assertIn("figma_asset_audit.py", content, prompt_file.name)
            self.assertIn("--requirement-id", content, prompt_file.name)
            self.assertIn("当前 R-xxx", content, prompt_file.name)
            self.assertIn("允许补齐", content, prompt_file.name)
            self.assertIn("禁止修改其他 R-xxx", content, prompt_file.name)
            self.assertIn("审计已通过", content, prompt_file.name)
            self.assertIn("本地物料不完整", content, prompt_file.name)

    def test_pipeline_does_not_auto_run_figma_asset_audit(self):
        pipeline_sources = [ROOT / "break_pipeline.py", ROOT / "main.py"]
        for source_file in pipeline_sources:
            content = source_file.read_text(encoding="utf-8")
            self.assertNotIn("figma_asset_audit", content, source_file.name)

    def test_developers_require_per_ac_figma_mcp_checklist_with_offline_reasons(self):
        for prompt_file in DEVELOPER_PROMPTS:
            content = prompt_file.read_text(encoding="utf-8")
            self.assertIn("Figma MCP 使用清单", content, prompt_file.name)
            self.assertIn("develop_report.md", content, prompt_file.name)
            self.assertIn("每个", content, prompt_file.name)
            self.assertIn("必须 UI AC", content, prompt_file.name)
            self.assertIn("勾选", content, prompt_file.name)
            self.assertIn("未勾选", content, prompt_file.name)
            self.assertIn("之前", content, prompt_file.name)
            self.assertIn("网络断开", content, prompt_file.name)
            self.assertIn("本地基线", content, prompt_file.name)

    def test_code_reviewers_judge_checklist_reasons_without_offline_loop(self):
        for prompt_file in CODE_REVIEW_PROMPTS:
            content = prompt_file.read_text(encoding="utf-8")
            self.assertIn("Figma MCP 使用清单", content, prompt_file.name)
            self.assertIn("未勾选", content, prompt_file.name)
            self.assertIn("理由", content, prompt_file.name)
            self.assertIn("独立调用", content, prompt_file.name)
            self.assertIn("网络正常", content, prompt_file.name)
            self.assertIn("网络断开", content, prompt_file.name)
            self.assertIn("不因未勾选本身", content, prompt_file.name)
            self.assertIn("changes_requested", content, prompt_file.name)
            self.assertIn("requirement_change", content, prompt_file.name)

    def test_requirement_reviewers_are_read_only_and_return_material_gaps_to_analyst(self):
        for prompt_file in ITEM_REQUIREMENTS_REVIEWER_PROMPTS:
            content = prompt_file.read_text(encoding="utf-8")
            self.assertIn("只读运行", content, prompt_file.name)
            self.assertIn("figma_asset_audit.py", content, prompt_file.name)
            self.assertIn("禁止修改", content, prompt_file.name)
            self.assertIn("changes_requested", content, prompt_file.name)
            self.assertIn("Requirements Analyst", content, prompt_file.name)

    def test_developers_can_supplement_scoped_materials_and_reaudit(self):
        for prompt_file in DEVELOPER_PROMPTS:
            content = prompt_file.read_text(encoding="utf-8")
            self.assertIn("只读运行", content, prompt_file.name)
            self.assertIn("figma_asset_audit.py", content, prompt_file.name)
            self.assertIn("禁止修改", content, prompt_file.name)
            self.assertIn("asset_manifest.json", content, prompt_file.name)
            self.assertIn("审计已通过", content, prompt_file.name)
            self.assertIn("允许按需补充下载当前 R-xxx", content, prompt_file.name)
            self.assertIn("补充后重新运行当前小需求审计", content, prompt_file.name)
            self.assertNotIn("不得自行下载", content, prompt_file.name)
            self.assertNotIn("物料只读消费边界", content, prompt_file.name)

    def test_code_reviewers_can_supplement_but_must_verify_implementation(self):
        for prompt_file in CODE_REVIEW_PROMPTS:
            content = prompt_file.read_text(encoding="utf-8")
            self.assertIn("只读运行", content, prompt_file.name)
            self.assertIn("figma_asset_audit.py", content, prompt_file.name)
            self.assertIn("禁止修改", content, prompt_file.name)
            self.assertIn("asset_manifest.json", content, prompt_file.name)
            self.assertIn("requirement_change", content, prompt_file.name)
            self.assertIn("Requirements Analyst", content, prompt_file.name)
            self.assertIn("允许按需补充下载当前 R-xxx", content, prompt_file.name)
            self.assertIn("不能仅因下载成功就通过", content, prompt_file.name)
            self.assertIn("补充后重新运行当前小需求审计", content, prompt_file.name)
            self.assertNotIn("或自行下载物料", content, prompt_file.name)
            self.assertNotIn("发现远程资产集合缺失则返回", content, prompt_file.name)

    def test_export_tags_are_advisory_and_upstream_allows_later_supplements(self):
        for prompt_file in Figma_ANALYSIS_PROMPTS + DEVELOPER_PROMPTS + REVIEWER_PROMPTS:
            content = prompt_file.read_text(encoding="utf-8")
            self.assertIn("可能多标或漏标", content, prompt_file.name)
            self.assertNotIn("是设计师交付意图的优先依据", content, prompt_file.name)
            self.assertIn("Developer 和 Code Reviewer 均允许", content, prompt_file.name)


if __name__ == "__main__":
    unittest.main()

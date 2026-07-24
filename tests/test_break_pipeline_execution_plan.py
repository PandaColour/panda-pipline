import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from break_pipeline import BreakPipeline


class BreakExecutionPlanTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.pipeline = BreakPipeline(self.temp_dir.name)
        self.requirements_dir = Path(self.pipeline.requirements_dir)
        self.requirements_dir.mkdir()
        self.index_file = Path(self.pipeline.requirements_index_file)
        self.index_file.write_text(
            "# 需求索引\\n\\n说明文字可变。\\n\\n"
            "| 顺序 | ID | 名称 | 状态 | 前置依赖 | 文件 | 验收摘要 |\\n"
            "| --- | --- | --- | --- | --- | --- | --- |\\n"
            "| 1 | R-001 | 登录 | 待实施 | 无 | R-001-login/user_requirements.md | 可登录 |\\n\\n"
            "| 其他表 | 不应由 Python 解析 |\\n"
            "| --- | --- |\\n"
            "| value | value |\\n",
            encoding="utf-8",
        )
        workspace = self.requirements_dir / "R-001-login"
        workspace.mkdir()
        (workspace / "user_requirements.md").write_text("# 登录\\n", encoding="utf-8")

    def _plan(self, status="待实施"):
        return {
            "schema_version": 1,
            "source_index_sha256": hashlib.sha256(self.index_file.read_bytes()).hexdigest(),
            "items": [{
                "order": 1,
                "id": "R-001",
                "name": "登录",
                "status": status,
                "dependencies": [],
                "requirements_file": "R-001-login/user_requirements.md",
                "acceptance_summary": "可登录",
            }],
        }

    def _demand_plan(self, status="待开发", demand_status="开发中"):
        plan = self._plan(status=status)
        plan.pop("schema_version")
        plan["demand"] = {
            "id": "D-001",
            "status": demand_status,
            "source": "登录需求",
        }
        return plan

    def _write_plan(self, plan):
        Path(self.pipeline.execution_plan_file).write_text(
            json.dumps(plan, ensure_ascii=False), encoding="utf-8"
        )

    def test_load_items_reads_json_plan_without_parsing_markdown_tables(self):
        self._write_plan(self._plan())

        items = self.pipeline._load_items()

        self.assertEqual([item.requirement_id for item in items], ["R-001"])

    def test_demand_aware_plan_without_schema_version_loads(self):
        self._write_plan(self._demand_plan())

        items = self.pipeline._load_items()

        saved_plan = json.loads(Path(self.pipeline.execution_plan_file).read_text(encoding="utf-8"))
        self.assertEqual(items[0].status, "待开发")
        self.assertNotIn("schema_version", saved_plan)
        self.assertEqual(saved_plan["demand"]["status"], "开发中")

    def test_legacy_plan_is_normalized_to_demand_aware_plan_without_schema_version(self):
        self._write_plan(self._plan(status="待实施"))

        self.pipeline._load_items()

        saved_plan = json.loads(Path(self.pipeline.execution_plan_file).read_text(encoding="utf-8"))
        self.assertNotIn("schema_version", saved_plan)
        self.assertEqual(saved_plan["demand"], {"id": "D-001", "status": "开发中", "source": ""})
        self.assertEqual(saved_plan["items"][0]["status"], "待开发")
        self.assertIsNone(saved_plan["items"][0]["pending_feedback"])

    def test_invalid_demand_status_is_rejected(self):
        self._write_plan(self._demand_plan(demand_status="随便写"))

        with patch.object(self.pipeline, "_create_agent", side_effect=AssertionError("normalizer should not run")), \
                self.assertRaisesRegex(ValueError, "未知需求整体状态"):
            self.pipeline._load_items()

    def test_persists_demand_status_and_item_pending_feedback(self):
        self._write_plan(self._demand_plan())

        self.pipeline.execution_plan.set_demand_status("记忆整理中")
        self.pipeline.execution_plan.set_pending_feedback(
            "R-001",
            kind="code_review",
            source_status="代码评审中",
            message="补充失败场景",
        )

        saved_plan = json.loads(Path(self.pipeline.execution_plan_file).read_text(encoding="utf-8"))
        self.assertEqual(saved_plan["demand"]["status"], "记忆整理中")
        self.assertEqual(saved_plan["items"][0]["pending_feedback"], {
            "kind": "code_review",
            "source_status": "代码评审中",
            "message": "补充失败场景",
        })

        self.pipeline.execution_plan.clear_pending_feedback("R-001")

        saved_plan = json.loads(Path(self.pipeline.execution_plan_file).read_text(encoding="utf-8"))
        self.assertIsNone(saved_plan["items"][0]["pending_feedback"])

    def test_load_items_normalizes_blocking_synonym_status(self):
        self._write_plan(self._plan(status="阻断（待外部契约）"))

        with patch.object(self.pipeline, "_create_agent", side_effect=AssertionError("normalizer should not run")):
            items = self.pipeline._load_items()

        self.assertEqual(items[0].status, "阻塞")
        saved_plan = json.loads(Path(self.pipeline.execution_plan_file).read_text(encoding="utf-8"))
        self.assertEqual(saved_plan["items"][0]["status"], "阻塞")

    def test_set_status_changes_json_without_modifying_markdown_index(self):
        self._write_plan(self._plan())
        original_index = self.index_file.read_bytes()

        self.pipeline._set_status("R-001", "开发中")

        saved_plan = json.loads(Path(self.pipeline.execution_plan_file).read_text(encoding="utf-8"))
        self.assertEqual(saved_plan["items"][0]["status"], "开发中")
        self.assertEqual(self.index_file.read_bytes(), original_index)

    def test_missing_plan_is_created_by_normalizer_agent(self):
        normalizer = MagicMock()

        def write_plan(_message):
            self._write_plan(self._plan())
            return ""

        normalizer.send_message.side_effect = write_plan
        with patch.object(self.pipeline, "_create_agent", return_value=normalizer) as create_agent:
            self.pipeline._ensure_execution_plan()

        create_agent.assert_called_once_with("执行索引规范化", "index_normalizer.md")
        self.assertIn(str(self.index_file), normalizer.send_message.call_args.args[0])
        self.assertEqual(self.pipeline._load_items()[0].requirement_id, "R-001")

    def test_normalizer_refusal_is_reported_without_masking_it_as_missing_plan(self):
        normalizer = MagicMock()
        normalizer.send_message.return_value = "索引表缺少可识别的需求条目"

        with patch.object(self.pipeline, "_create_agent", return_value=normalizer), \
                self.assertRaisesRegex(ValueError, "索引表缺少可识别的需求条目"):
            self.pipeline._ensure_execution_plan()

    def test_stale_plan_is_replaced_by_normalizer_agent(self):
        stale_plan = self._plan()
        stale_plan["source_index_sha256"] = "0" * 64
        self._write_plan(stale_plan)
        normalizer = MagicMock()
        normalizer.send_message.side_effect = lambda _message: self._write_plan(self._plan())

        with patch.object(self.pipeline, "_create_agent", return_value=normalizer):
            self.pipeline._ensure_execution_plan()

        normalizer.send_message.assert_called_once()
        self.assertEqual(self.pipeline._load_items()[0].filename, "R-001-login/user_requirements.md")

    def test_load_items_rejects_file_outside_requirements_directory(self):
        plan = self._plan()
        plan["items"][0]["requirements_file"] = "../escape/user_requirements.md"
        self._write_plan(plan)

        with self.assertRaisesRegex(ValueError, "requirements"):
            self.pipeline._load_items()

    def test_load_items_rejects_absolute_requirements_file(self):
        plan = self._plan()
        plan["items"][0]["requirements_file"] = str(
            self.requirements_dir / "R-001-login" / "user_requirements.md"
        )
        self._write_plan(plan)

        with self.assertRaisesRegex(ValueError, "相对路径"):
            self.pipeline._load_items()

    def test_load_items_rejects_noncanonical_requirements_file(self):
        plan = self._plan()
        plan["items"][0]["requirements_file"] = "temporary/../R-001-login/user_requirements.md"
        self._write_plan(plan)

        with self.assertRaisesRegex(ValueError, "相对路径"):
            self.pipeline._load_items()

    def test_load_items_renormalizes_stale_plan_after_index_changes(self):
        self._write_plan(self._plan())
        self.index_file.write_text("# 人工更新后的索引\\n", encoding="utf-8")
        normalizer = MagicMock()
        normalizer.send_message.side_effect = lambda _message: self._write_plan(self._plan())

        with patch.object(self.pipeline, "_create_agent", return_value=normalizer):
            items = self.pipeline._load_items()

        normalizer.send_message.assert_called_once()
        self.assertEqual(items[0].requirement_id, "R-001")

    def test_renormalization_preserves_status_for_unchanged_item(self):
        self._write_plan(self._plan(status="已完成"))
        self.index_file.write_text("# 仅修改说明文字\\n", encoding="utf-8")
        normalizer = MagicMock()
        normalizer.send_message.side_effect = lambda _message: self._write_plan(self._plan(status="待实施"))

        with patch.object(self.pipeline, "_create_agent", return_value=normalizer):
            items = self.pipeline._load_items()

        self.assertEqual(items[0].status, "已完成")

    def test_renormalization_preserves_pending_feedback_for_unchanged_item(self):
        self._write_plan(self._demand_plan(status="开发中"))
        self.pipeline.execution_plan.set_pending_feedback(
            "R-001",
            kind="human",
            source_status="待人工确认",
            message="保留这条反馈",
        )
        self.index_file.write_text("# 仅修改说明文字\\n", encoding="utf-8")
        normalizer = MagicMock()
        normalizer.send_message.side_effect = lambda _message: self._write_plan(self._demand_plan(status="待开发"))

        with patch.object(self.pipeline, "_create_agent", return_value=normalizer):
            self.pipeline._load_items()

        saved_plan = json.loads(Path(self.pipeline.execution_plan_file).read_text(encoding="utf-8"))
        self.assertEqual(saved_plan["items"][0]["pending_feedback"]["message"], "保留这条反馈")

    def test_load_items_rejects_non_string_dependency_with_value_error(self):
        plan = self._plan()
        plan["items"][0]["dependencies"] = [1]
        self._write_plan(plan)
        normalizer = MagicMock()

        with patch.object(self.pipeline, "_create_agent", return_value=normalizer), \
                self.assertRaisesRegex(ValueError, "前置依赖"):
            self.pipeline._load_items()

        normalizer.send_message.assert_called_once()


if __name__ == "__main__":
    unittest.main()

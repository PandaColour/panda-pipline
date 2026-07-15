import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from agents import Agent
from break_pipeline import BreakPipeline


class BreakPipelineTests(unittest.TestCase):
    def test_agent_loads_prompt_from_explicit_prompt_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            prompt_dir = Path(directory)
            (prompt_dir / "break.md").write_text("break prompt", encoding="utf-8")

            agent = Agent(
                "breakdown",
                "break.md",
                directory,
                prompt_dir=str(prompt_dir),
            )

        self.assertEqual(agent.system_prompt, "break prompt")

    def test_create_agent_uses_break_prompt_directory(self):
        pipeline = BreakPipeline("workspace")

        with patch("break_pipeline.Agent") as agent_class:
            pipeline._create_agent("需求拆分", "requirement_breaker.md")

        self.assertEqual(
            agent_class.call_args.kwargs["prompt_dir"],
            pipeline.prompt_dir,
        )

    def test_breakdown_retries_reviewer_and_human_feedback(self):
        with tempfile.TemporaryDirectory() as work_dir:
            pipeline = BreakPipeline(work_dir)
            breaker = MagicMock()
            reviewer = MagicMock()
            reviewer.send_message.side_effect = ["请补充验收标准", "拆分方案通过", "拆分方案通过"]

            with patch.object(pipeline, "_create_agent", side_effect=[breaker, reviewer]), \
                    patch("builtins.input", return_value="大需求"), \
                    patch("break_pipeline.human_gate", side_effect=["补充边界", None]) as gate:
                pipeline._run_breakdown()

        self.assertEqual(breaker.send_message.call_count, 3)
        self.assertIn(pipeline.requirements_index_file, gate.call_args_list[0].args)

    def test_empty_breakdown_review_is_an_error(self):
        with tempfile.TemporaryDirectory() as work_dir:
            pipeline = BreakPipeline(work_dir)
            breaker = MagicMock()
            reviewer = MagicMock()
            reviewer.send_message.return_value = ""

            with patch.object(pipeline, "_create_agent", side_effect=[breaker, reviewer]), \
                    patch("builtins.input", return_value="大需求"):
                with self.assertRaisesRegex(RuntimeError, "拆分评审未返回结论"):
                    pipeline._run_breakdown()

    def test_unknown_dependency_stops_before_development(self):
        with tempfile.TemporaryDirectory() as work_dir:
            pipeline = BreakPipeline(work_dir)
            self._write_requirement_files(work_dir, "R-001")
            self._write_index(work_dir, [(1, "R-001", "待实施", "R-999", "001-first.md")])

            with self.assertRaisesRegex(ValueError, "未知前置依赖: R-999"):
                pipeline._run_execution()

    def test_in_progress_item_is_selected_after_restart(self):
        item = BreakPipeline("workspace")
        items = [
            type("Item", (), {"requirement_id": "R-001", "status": "开发中", "dependencies": []})(),
        ]

        self.assertEqual(item._next_runnable_item(items).requirement_id, "R-001")

    def test_unrunnable_pending_item_is_marked_blocked(self):
        with tempfile.TemporaryDirectory() as work_dir:
            pipeline = BreakPipeline(work_dir)
            self._write_requirement_files(work_dir, "R-001", "R-002")
            self._write_index(work_dir, [
                (1, "R-001", "待审核", "无", "001-first.md"),
                (2, "R-002", "待实施", "R-001", "002-second.md"),
            ])

            with self.assertRaisesRegex(RuntimeError, "没有可执行的小需求"):
                pipeline._run_execution()

            self.assertIn("| R-002 | name | 阻塞 |", Path(pipeline.requirements_index_file).read_text(encoding="utf-8"))

    def test_index_rejects_paths_outside_requirements_directory(self):
        with tempfile.TemporaryDirectory() as work_dir:
            pipeline = BreakPipeline(work_dir)
            self._write_requirement_files(work_dir, "R-001")
            self._write_index(work_dir, [(1, "R-001", "待实施", "无", "../001-first.md")])

            with self.assertRaisesRegex(ValueError, "需求文件必须位于 requirements 目录"):
                pipeline._validate_items(pipeline._load_items())

    def test_index_rejects_wrong_header(self):
        with tempfile.TemporaryDirectory() as work_dir:
            pipeline = BreakPipeline(work_dir)
            self._write_requirement_files(work_dir, "R-001")
            Path(pipeline.requirements_index_file).write_text(
                "| order | ID | 名称 | 状态 | 前置依赖 | 文件 | 验收摘要 |\n"
                "| --- | --- | --- | --- | --- | --- | --- |\n"
                "| 1 | R-001 | name | 待实施 | 无 | 001-first.md | ok |\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "索引表头不符合约定"):
                pipeline._load_items()

    def test_execution_creates_reports_directory(self):
        with tempfile.TemporaryDirectory() as work_dir:
            pipeline = BreakPipeline(work_dir)
            self._write_requirement_files(work_dir, "R-001")
            self._write_index(work_dir, [(1, "R-001", "待实施", "无", "001-first.md")])
            developer, tester, reviewer = MagicMock(), MagicMock(), MagicMock()
            reviewer.send_message.return_value = "任务完成"
            with patch.object(pipeline, "_create_agent", side_effect=[MagicMock(), MagicMock(), developer, tester, reviewer]), \
                    patch("break_pipeline.human_gate", return_value=None):
                pipeline._run_execution()

            self.assertTrue(Path(pipeline.reports_dir).is_dir())

    def test_run_resumes_only_human_approved_breakdown(self):
        with tempfile.TemporaryDirectory() as work_dir:
            pipeline = BreakPipeline(work_dir)
            Path(pipeline.requirements_dir).mkdir()
            Path(pipeline.requirements_index_file).write_text("existing", encoding="utf-8")
            Path(pipeline.breakdown_approval_file).write_text("approved\n", encoding="utf-8")
            with patch.object(pipeline, "_run_breakdown") as breakdown, \
                    patch.object(pipeline, "_run_execution") as execution, \
                    patch.object(pipeline, "_run_final_reflection"):
                pipeline.run()

        breakdown.assert_not_called()
        execution.assert_called_once_with()

    def test_existing_unapproved_index_returns_to_breakdown_review(self):
        with tempfile.TemporaryDirectory() as work_dir:
            pipeline = BreakPipeline(work_dir)
            Path(pipeline.requirements_dir).mkdir()
            Path(pipeline.requirements_index_file).write_text("existing", encoding="utf-8")
            with patch.object(pipeline, "_run_breakdown") as breakdown, \
                    patch.object(pipeline, "_run_execution") as execution, \
                    patch.object(pipeline, "_run_final_reflection"):
                pipeline.run()

        breakdown.assert_called_once_with()
        execution.assert_called_once_with()

    def test_reviewer_receives_review_report_path(self):
        with tempfile.TemporaryDirectory() as work_dir:
            pipeline = BreakPipeline(work_dir)
            self._write_requirement_files(work_dir, "R-001")
            self._write_index(work_dir, [(1, "R-001", "待实施", "无", "001-first.md")])
            developer, tester, reviewer = MagicMock(), MagicMock(), MagicMock()
            reviewer.send_message.return_value = "任务完成"
            with patch.object(pipeline, "_create_agent", side_effect=[MagicMock(), MagicMock(), developer, tester, reviewer]), \
                    patch("break_pipeline.human_gate", return_value=None):
                pipeline._run_execution()

            self.assertIn("R-001-review.md", reviewer.send_message.call_args.args[0])

    def test_waiting_human_item_resumes_at_human_gate(self):
        with tempfile.TemporaryDirectory() as work_dir:
            pipeline = BreakPipeline(work_dir)
            self._write_requirement_files(work_dir, "R-001")
            self._write_index(work_dir, [(1, "R-001", "待人工确认", "无", "001-first.md")])
            developer, tester, reviewer = MagicMock(), MagicMock(), MagicMock()
            with patch.object(pipeline, "_create_agent", side_effect=[MagicMock(), MagicMock(), developer, tester, reviewer]), \
                    patch("break_pipeline.human_gate", return_value=None):
                pipeline._run_execution()

            developer.send_message.assert_not_called()
            self.assertIn("已完成", Path(pipeline.requirements_index_file).read_text(encoding="utf-8"))

    def test_item_requirement_gates_run_before_development(self):
        with tempfile.TemporaryDirectory() as work_dir:
            pipeline = BreakPipeline(work_dir)
            self._write_requirement_files(work_dir, "R-001")
            self._write_index(work_dir, [(1, "R-001", "待需求分析", "无", "001-first.md")])
            analyst, requirements_reviewer = MagicMock(), MagicMock()
            developer, tester, code_reviewer = MagicMock(), MagicMock(), MagicMock()
            requirements_reviewer.send_message.return_value = "同意方案"
            code_reviewer.send_message.return_value = "任务完成"
            with patch.object(
                pipeline,
                "_create_agent",
                side_effect=[analyst, requirements_reviewer, developer, tester, code_reviewer],
            ), patch("break_pipeline.human_gate", side_effect=[None, None]):
                pipeline._run_execution()

            self.assertEqual(analyst.send_message.call_count, 1)
            self.assertEqual(requirements_reviewer.send_message.call_count, 1)
            self.assertEqual(developer.send_message.call_count, 1)
            self.assertIn("已完成", Path(pipeline.requirements_index_file).read_text(encoding="utf-8"))

    def test_item_requirement_review_feedback_retries_only_current_analyst(self):
        with tempfile.TemporaryDirectory() as work_dir:
            pipeline = BreakPipeline(work_dir)
            self._write_requirement_files(work_dir, "R-001")
            self._write_index(work_dir, [(1, "R-001", "待需求分析", "无", "001-first.md")])
            analyst, requirements_reviewer = MagicMock(), MagicMock()
            developer, tester, code_reviewer = MagicMock(), MagicMock(), MagicMock()
            requirements_reviewer.send_message.side_effect = ["补充异常场景", "同意方案"]
            code_reviewer.send_message.return_value = "任务完成"
            with patch.object(
                pipeline,
                "_create_agent",
                side_effect=[analyst, requirements_reviewer, developer, tester, code_reviewer],
            ), patch("break_pipeline.human_gate", side_effect=[None, None]):
                pipeline._run_execution()

            self.assertEqual(analyst.send_message.call_count, 2)
            self.assertIn("补充异常场景", analyst.send_message.call_args.args[0])

    def test_requirement_change_from_code_review_returns_to_requirement_gates(self):
        with tempfile.TemporaryDirectory() as work_dir:
            pipeline = BreakPipeline(work_dir)
            self._write_requirement_files(work_dir, "R-001")
            self._write_index(work_dir, [(1, "R-001", "待实施", "无", "001-first.md")])
            analyst, requirements_reviewer = MagicMock(), MagicMock()
            developer, tester, code_reviewer = MagicMock(), MagicMock(), MagicMock()
            requirements_reviewer.send_message.return_value = "同意方案"
            code_reviewer.send_message.side_effect = ["需求变更: 补充失败场景", "任务完成"]
            with patch.object(
                pipeline,
                "_create_agent",
                side_effect=[analyst, requirements_reviewer, developer, tester, code_reviewer],
            ), patch("break_pipeline.human_gate", side_effect=[None, None]):
                pipeline._run_execution()

            self.assertEqual(analyst.send_message.call_count, 1)
            self.assertEqual(developer.send_message.call_count, 2)

    def test_human_feedback_retries_only_current_item(self):
        with tempfile.TemporaryDirectory() as work_dir:
            pipeline = BreakPipeline(work_dir)
            self._write_requirement_files(work_dir, "R-001", "R-002")
            self._write_index(work_dir, [
                (1, "R-001", "待实施", "无", "001-first.md"),
                (2, "R-002", "待实施", "R-001", "002-second.md"),
            ])
            developer, tester, reviewer = MagicMock(), MagicMock(), MagicMock()
            reviewer.send_message.return_value = "任务完成"
            with patch.object(pipeline, "_create_agent", side_effect=[MagicMock(), MagicMock(), developer, tester, reviewer]), \
                    patch("break_pipeline.human_gate", side_effect=["修正 R-001", None, None]):
                pipeline._run_execution()

        self.assertEqual(developer.send_message.call_count, 3)
        retry_prompt = developer.send_message.call_args_list[1].args[0]
        self.assertIn("R-001", retry_prompt)
        self.assertNotIn("R-002", retry_prompt)

    @staticmethod
    def _write_requirement_files(work_dir, *ids):
        folder = Path(work_dir) / "requirements"
        folder.mkdir()
        for number, requirement_id in enumerate(ids, 1):
            (folder / f"{number:03d}-{'first' if number == 1 else 'second'}.md").write_text(
                f"# {requirement_id}\n", encoding="utf-8"
            )

    @staticmethod
    def _write_index(work_dir, rows):
        lines = [
            "| 顺序 | ID | 名称 | 状态 | 前置依赖 | 文件 | 验收摘要 |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
        for order, requirement_id, status, dependencies, filename in rows:
            lines.append(
                f"| {order} | {requirement_id} | name | {status} | {dependencies} | {filename} | ok |"
            )
        (Path(work_dir) / "requirements" / "index.md").write_text(
            "\n".join(lines) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    unittest.main()

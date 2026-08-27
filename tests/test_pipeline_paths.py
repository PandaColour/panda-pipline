import os
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import pipeline
import static_scan
from config import SYSTEM_PROMPT_DIR
from pipeline import Pipeline


class PipelinePathTests(unittest.TestCase):

    def test_skip_human_is_forwarded_to_every_human_gate(self):
        pipeline = Pipeline("/tmp/target", skip_human=True)

        with patch("pipeline.human_gate", return_value=None) as gate:
            pipeline._human_gate("测试", "/tmp/report.md")

        gate.assert_called_once_with("测试", "/tmp/report.md", skip_human=True)
    def test_initializes_full_report_paths(self):
        pipeline = Pipeline("relative-workspace")
        work_dir = os.path.abspath("relative-workspace")
        requirement_dir = os.path.join(work_dir, "requirements", "R-001-main")

        self.assertEqual(pipeline.work_dir, work_dir)
        self.assertEqual(pipeline.requirements_dir, os.path.join(work_dir, "requirements"))
        self.assertEqual(pipeline.requirement_dir, requirement_dir)
        self.assertEqual(pipeline.execution_plan_file, os.path.join(work_dir, "requirements", "execution_plan.json"))
        self.assertEqual(pipeline.user_requirements_file, os.path.join(requirement_dir, "user_requirements.md"))
        self.assertEqual(pipeline.develop_report_file, os.path.join(requirement_dir, "develop_report.md"))
        self.assertEqual(pipeline.test_report_file, os.path.join(requirement_dir, "test_report.md"))

    def test_development_prompts_use_full_report_paths(self):
        with tempfile.TemporaryDirectory() as work_dir:
            pipeline = Pipeline(work_dir)

            developer = MagicMock()
            code_reviewer = MagicMock()
            code_reviewer.send_message.return_value = "任务完成"

            agents = {
                "代码开发": developer,
                "代码验证审查": code_reviewer,
            }
            created = []

            def create_agent(*args):
                created.append(args)
                return agents[args[0]]

            with patch.object(pipeline, "_create_agent", side_effect=create_agent), \
                    patch("pipeline.human_gate", return_value=None):
                pipeline._run_stage_2_development()

            self.assertEqual(
                created,
                [
                    ("代码开发", "code_developer.md"),
                    ("代码验证审查", "code_reviewer.md"),
                ],
            )
            self.assertTrue(Path(pipeline.requirement_dir).is_dir())

            developer_prompt = developer.send_message.call_args.args[0]
            reviewer_prompt = code_reviewer.send_message.call_args.args[0]

            self.assertIn(pipeline.user_requirements_file, developer_prompt)
            self.assertIn(pipeline.develop_report_file, developer_prompt)
            self.assertIn("自测", developer_prompt)
            self.assertNotIn("不要编写测试代码", developer_prompt)
            self.assertIn(pipeline.user_requirements_file, reviewer_prompt)
            self.assertIn(pipeline.develop_report_file, reviewer_prompt)
            self.assertIn(pipeline.test_report_file, reviewer_prompt)
            self.assertIn("执行必要测试", reviewer_prompt)

    def test_create_agent_always_uses_pipeline_root(self):
        pipeline = Pipeline("relative-workspace")

        with patch.object(pipeline, "_agent_status", return_value="开发中") as agent_status, \
                patch("pipeline.Agent") as agent_class:
            created = pipeline._create_agent("需求分析", "requirements_analyst.md")

        self.assertIsNotNone(created)
        call = agent_class.call_args
        self.assertEqual(call.args, ("需求分析", "requirements_analyst.md", pipeline.work_dir))
        self.assertEqual(call.kwargs["add_dirs"], None)
        self.assertEqual(call.kwargs["agent_type"], "cursor")
        self.assertEqual(call.kwargs["prompt_dir"], pipeline.prompt_dir)
        self.assertEqual(call.kwargs["status_provider"](), "开发中")
        agent_status.assert_called_once_with()

    def test_memory_curation_template_lives_in_system_prompt(self):
        template = Path(SYSTEM_PROMPT_DIR) / "memory_curation.md"

        self.assertTrue(template.is_file())
        content = template.read_text(encoding="utf-8")
        for placeholder in (
            "{opening}",
            "{read_instruction}",
            "{curation_scope}",
            "{execution_plan_file}",
            "{closing_instruction}",
        ):
            self.assertIn(placeholder, content)
        self.assertIn("记忆整理目的", content)
        self.assertIn("为后续类似项目从0到1提供指导", content)
        self.assertIn("为后续需求提供代码索引", content)
        self.assertIn("当前源码", content)
        self.assertIn("长期 memory 不得写入 R-xxx", content)

    def test_final_reflection_renders_system_prompt_template(self):
        with tempfile.TemporaryDirectory() as work_dir, tempfile.TemporaryDirectory() as prompt_dir:
            template = Path(prompt_dir) / "memory_curation.md"
            template.write_text(
                "CUSTOM SYSTEM TEMPLATE\n"
                "{opening}\n"
                "{read_instruction}\n"
                "{curation_scope}\n"
                "{execution_plan_file}\n"
                "{closing_instruction}\n",
                encoding="utf-8",
            )
            pipeline = Pipeline(work_dir)
            pipeline.prompt_dir = prompt_dir
            analyst = MagicMock()
            developer = MagicMock()
            pipeline.agents = {
                "需求分析": analyst,
                "代码开发": developer,
            }

            pipeline._run_final_reflection()

            analyst_prompt = analyst.send_message.call_args.args[0]
            developer_prompt = developer.send_message.call_args.args[0]
            for prompt in (analyst_prompt, developer_prompt):
                self.assertIn("CUSTOM SYSTEM TEMPLATE", prompt)
                self.assertIn(pipeline.execution_plan_file, prompt)
                self.assertIn("收到记忆整理指令", prompt)

    def test_run_passes_user_idea_into_requirements_stage(self):
        pipeline = Pipeline("relative-workspace")

        with patch.object(pipeline, "_ensure_execution_plan") as ensure_plan, \
                patch.object(pipeline, "_run_stage_1_requirements") as requirements, \
                patch.object(pipeline, "_run_stage_2_development") as development, \
                patch.object(pipeline, "_run_final_reflection") as reflection, \
                patch.object(pipeline, "_active_requirements_complete", side_effect=[False, True]), \
                patch.object(pipeline, "_item_status", side_effect=["需求分析中", "待开发", "记忆整理中"]), \
                patch.object(pipeline, "_set_demand_status"), \
                patch.object(pipeline, "_set_status"), \
                patch.object(pipeline, "_archive_completed_requirements"):
            pipeline.run("新增后台管理")

        ensure_plan.assert_called_once_with("新增后台管理")
        requirements.assert_called_once_with()
        development.assert_called_once_with()
        reflection.assert_called_once_with()

    def test_requirements_stage_does_not_create_role_directory(self):
        with tempfile.TemporaryDirectory() as work_dir:
            pipeline = Pipeline(work_dir)
            analyst = MagicMock()
            analyst.display_name = "需求分析agent(cursor)"
            reviewer = MagicMock()
            reviewer.send_message.return_value = "同意方案"
            agents = {"需求分析": analyst, "需求审查": reviewer}
            created = []

            def create_agent(*args):
                created.append(args)
                return agents[args[0]]

            with patch.object(pipeline, "_create_agent", side_effect=create_agent), \
                    patch("pipeline.human_gate", return_value=None):
                pipeline._run_stage_1_requirements("new project")

            self.assertEqual(
                created,
                [
                    ("需求分析", "requirements_analyst.md"),
                    ("需求审查", "requirements_reviewer.md"),
                ],
            )
            self.assertTrue(Path(pipeline.requirement_dir).is_dir())

    def test_requirement_review_auto_passes_after_three_failed_agent_reviews(self):
        with tempfile.TemporaryDirectory() as work_dir:
            pipeline = Pipeline(work_dir)
            analyst = MagicMock()
            analyst.display_name = "需求分析agent(cursor)"
            reviewer = MagicMock()
            reviewer.send_message.side_effect = ["缺少范围", "仍缺少验收", "还不完整"]
            agents = {"需求分析": analyst, "需求审查": reviewer}

            with patch.object(pipeline, "_create_agent", side_effect=lambda name, prompt: agents[name]), \
                    patch("pipeline.human_gate", return_value=None) as gate:
                pipeline._run_stage_1_requirements("new project")

            self.assertEqual(reviewer.send_message.call_count, 3)
            self.assertEqual(analyst.send_message.call_count, 3)
            self.assertIn("缺少范围", analyst.send_message.call_args_list[1].args[0])
            self.assertIn("仍缺少验收", analyst.send_message.call_args_list[2].args[0])
            gate.assert_called_once_with(
                "1. 需求分析",
                pipeline.user_requirements_file,
                skip_human=False,
                feedback_target="需求分析agent(cursor)",
            )

    def test_ensure_execution_plan_creates_single_requirement_under_requirements(self):
        with tempfile.TemporaryDirectory() as work_dir:
            pipeline = Pipeline(work_dir)

            pipeline._ensure_execution_plan("new project")

            self.assertTrue(Path(pipeline.requirements_index_file).is_file())
            self.assertTrue(Path(pipeline.requirement_dir).is_dir())
            plan = json.loads(Path(pipeline.execution_plan_file).read_text(encoding="utf-8"))
            self.assertNotIn("schema_version", plan)
            self.assertEqual(plan["demand"]["source"], "new project")
            self.assertEqual(plan["items"][0]["id"], "R-001")
            self.assertEqual(plan["items"][0]["status"], "需求分析中")
            self.assertEqual(plan["items"][0]["requirements_file"], "R-001-main/user_requirements.md")

    def test_restart_at_code_review_runs_reviewer_without_rerunning_developer(self):
        with tempfile.TemporaryDirectory() as work_dir:
            pipeline = Pipeline(work_dir)
            pipeline._ensure_execution_plan("new project")
            pipeline._set_status("代码评审中")
            developer = MagicMock()
            code_reviewer = MagicMock()
            code_reviewer.send_message.return_value = "任务完成"
            agents = {
                "代码开发": developer,
                "代码验证审查": code_reviewer,
            }

            with patch.object(pipeline, "_create_agent", side_effect=lambda name, prompt: agents[name]), \
                    patch("pipeline.human_gate", return_value=None):
                pipeline._run_stage_2_development()

            developer.send_message.assert_not_called()
            code_reviewer.send_message.assert_called_once()
            plan = json.loads(Path(pipeline.execution_plan_file).read_text(encoding="utf-8"))
            self.assertEqual(plan["items"][0]["status"], "记忆整理中")

    def test_static_scan_status_is_valid(self):
        self.assertIn("静态扫描中", pipeline.VALID_STATUSES)

    def test_development_reviewer_prompt_includes_static_scan_report(self):
        with tempfile.TemporaryDirectory() as work_dir:
            pipeline = Pipeline(work_dir)
            developer = MagicMock()
            code_reviewer = MagicMock()
            code_reviewer.send_message.return_value = "任务完成"
            agents = {
                "代码开发": developer,
                "代码验证审查": code_reviewer,
            }

            with patch.object(pipeline, "_create_agent", side_effect=lambda name, prompt: agents[name]), \
                    patch.object(pipeline, "_run_static_scan"), \
                    patch("pipeline.human_gate", return_value=None):
                pipeline._run_stage_2_development()

            reviewer_prompt = code_reviewer.send_message.call_args.args[0]
            self.assertIn(pipeline.static_scan_report_file, reviewer_prompt)

    def test_stage2_passes_through_static_scan_status(self):
        with tempfile.TemporaryDirectory() as work_dir:
            pipeline = Pipeline(work_dir)
            pipeline._ensure_execution_plan("new project")
            developer = MagicMock()
            code_reviewer = MagicMock()
            code_reviewer.send_message.return_value = "任务完成"
            agents = {
                "代码开发": developer,
                "代码验证审查": code_reviewer,
            }
            statuses = []
            original_set_status = pipeline._set_status

            def recording_set_status(status):
                statuses.append(status)
                original_set_status(status)

            with patch.object(pipeline, "_create_agent", side_effect=lambda name, prompt: agents[name]), \
                    patch.object(pipeline, "_set_status", side_effect=recording_set_status), \
                    patch.object(pipeline, "_run_static_scan"), \
                    patch("pipeline.human_gate", return_value=None):
                pipeline._run_stage_2_development()

            self.assertIn("静态扫描中", statuses)
            self.assertLess(statuses.index("静态扫描中"), statuses.index("代码评审中"))

    def test_restart_at_static_scan_resumes_scan_then_review(self):
        with tempfile.TemporaryDirectory() as work_dir:
            pipeline = Pipeline(work_dir)
            pipeline._ensure_execution_plan("new project")
            pipeline._set_status("静态扫描中")
            developer = MagicMock()
            code_reviewer = MagicMock()
            code_reviewer.send_message.return_value = "任务完成"
            agents = {
                "代码开发": developer,
                "代码验证审查": code_reviewer,
            }

            with patch.object(pipeline, "_create_agent", side_effect=lambda name, prompt: agents[name]), \
                    patch.object(pipeline, "_run_static_scan") as scan, \
                    patch("pipeline.human_gate", return_value=None):
                pipeline._run_stage_2_development()

            scan.assert_called_once()
            developer.send_message.assert_not_called()
            plan = json.loads(Path(pipeline.execution_plan_file).read_text(encoding="utf-8"))
            self.assertEqual(plan["items"][0]["status"], "记忆整理中")

    def test_restart_at_code_review_skips_rescan_when_report_exists(self):
        with tempfile.TemporaryDirectory() as work_dir:
            pipeline = Pipeline(work_dir)
            pipeline._ensure_execution_plan("new project")
            pipeline._set_status("代码评审中")
            with open(pipeline.static_scan_report_file, "w", encoding="utf-8") as report_file:
                report_file.write("# 代码静态扫描报告\n")
            developer = MagicMock()
            code_reviewer = MagicMock()
            code_reviewer.send_message.return_value = "任务完成"
            agents = {
                "代码开发": developer,
                "代码验证审查": code_reviewer,
            }

            with patch.object(pipeline, "_create_agent", side_effect=lambda name, prompt: agents[name]), \
                    patch.object(pipeline, "_run_static_scan") as scan, \
                    patch("pipeline.human_gate", return_value=None):
                pipeline._run_stage_2_development()

            scan.assert_not_called()
            code_reviewer.send_message.assert_called_once()

    def test_restart_at_code_review_rescans_when_report_missing(self):
        with tempfile.TemporaryDirectory() as work_dir:
            pipeline = Pipeline(work_dir)
            pipeline._ensure_execution_plan("new project")
            pipeline._set_status("代码评审中")
            developer = MagicMock()
            code_reviewer = MagicMock()
            code_reviewer.send_message.return_value = "任务完成"
            agents = {
                "代码开发": developer,
                "代码验证审查": code_reviewer,
            }

            with patch.object(pipeline, "_create_agent", side_effect=lambda name, prompt: agents[name]), \
                    patch.object(pipeline, "_run_static_scan") as scan, \
                    patch("pipeline.human_gate", return_value=None):
                pipeline._run_stage_2_development()

            scan.assert_called_once()

    def test_run_dispatches_static_scan_status_to_stage2(self):
        with tempfile.TemporaryDirectory() as work_dir:
            pipeline = Pipeline(work_dir)
            pipeline._ensure_execution_plan("new project")
            pipeline._set_status("静态扫描中")

            with patch.object(pipeline, "_run_stage_1_requirements") as requirements, \
                    patch.object(pipeline, "_run_stage_2_development") as development, \
                    patch.object(pipeline, "_run_final_reflection") as reflection:
                pipeline.run("new project")

            requirements.assert_not_called()
            development.assert_called_once_with()
            reflection.assert_not_called()

    def test_static_scan_skips_when_no_source_files(self):
        with tempfile.TemporaryDirectory() as work_dir:
            report_path = os.path.join(work_dir, "static_scan_report.md")

            with patch.object(static_scan, "_run_detekt") as detekt, \
                    patch.object(static_scan, "_run_ruff") as ruff, \
                    patch.object(static_scan, "_run_cpd") as cpd:
                static_scan.run_static_scan(work_dir, report_path)

            detekt.assert_not_called()
            ruff.assert_not_called()
            cpd.assert_not_called()
            with open(report_path, encoding="utf-8") as report_file:
                content = report_file.read()
            self.assertIn("跳过静态扫描", content)

    def test_static_scan_combines_language_rules_and_cpd(self):
        with tempfile.TemporaryDirectory() as work_dir:
            kt_dir = os.path.join(work_dir, "app", "src", "main")
            os.makedirs(kt_dir)
            with open(os.path.join(kt_dir, "Foo.kt"), "w", encoding="utf-8") as f:
                f.write("package demo\nobject Foo {}\n")
            py_dir = os.path.join(work_dir, "backend")
            os.makedirs(py_dir)
            with open(os.path.join(py_dir, "main.py"), "w", encoding="utf-8") as f:
                f.write("def main():\n    pass\n")
            report_path = os.path.join(work_dir, "static_scan_report.md")

            with patch.object(static_scan, "_run_detekt", return_value="MagicNumber - 1000 at A.kt"), \
                    patch.object(static_scan, "_run_ruff", return_value="PLR2004 at main.py"), \
                    patch.object(static_scan, "_run_cpd", return_value="Found a duplication in A.kt and B.kt"):
                static_scan.run_static_scan(work_dir, report_path)

            with open(report_path, encoding="utf-8") as report_file:
                content = report_file.read()
            self.assertIn("Kotlin", content)
            self.assertIn("MagicNumber", content)
            self.assertIn("Python", content)
            self.assertIn("PLR2004", content)
            self.assertIn("代码重复", content)

    def test_run_detekt_returns_note_when_tool_missing(self):
        with patch("static_scan.shutil.which", return_value=None):
            output = static_scan._run_detekt(["/tmp/Foo.kt"])

        self.assertIn("未安装 detekt", output)

    def test_run_cpd_returns_note_when_tool_missing(self):
        with patch("static_scan.shutil.which", return_value=None):
            output = static_scan._run_cpd("kotlin", ["/tmp/Foo.kt"])

        self.assertIn("未安装 pmd", output)

    def test_scan_config_exclude_dirs_extend_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = os.path.join(tmp, "scan_config.json")
            with open(config_path, "w", encoding="utf-8") as config_file:
                config_file.write(json.dumps({"exclude_dirs": ["mock-server", "aux_tool"]}))

            with patch.object(static_scan, "SCAN_CONFIG_PATH", config_path):
                excluded = static_scan.exclude_dirs()

            self.assertIn("mock-server", excluded)
            self.assertIn("aux_tool", excluded)
            self.assertIn("build", excluded)

    def test_run_static_scan_excludes_configured_dirs(self):
        with tempfile.TemporaryDirectory() as work_dir, tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(work_dir, "app"))
            with open(os.path.join(work_dir, "app", "main.py"), "w", encoding="utf-8") as f:
                f.write("def main():\n    return 1000\n")
            os.makedirs(os.path.join(work_dir, "mock-server"))
            with open(os.path.join(work_dir, "mock-server", "aux.py"), "w", encoding="utf-8") as f:
                f.write("def aux():\n    return 2000\n")
            config_path = os.path.join(tmp, "scan_config.json")
            with open(config_path, "w", encoding="utf-8") as config_file:
                config_file.write(json.dumps({"exclude_dirs": ["mock-server"]}))
            report_path = os.path.join(work_dir, "static_scan_report.md")
            captured = {}

            def fake_ruff(files):
                captured["files"] = list(files)
                return ""

            with patch.object(static_scan, "SCAN_CONFIG_PATH", config_path), \
                    patch.object(static_scan, "_run_ruff", side_effect=fake_ruff):
                static_scan.run_static_scan(work_dir, report_path)

            self.assertTrue(any(file.endswith("main.py") for file in captured["files"]))
            self.assertFalse(any("mock-server" in file for file in captured["files"]))

    def test_run_after_process_restart_resumes_from_execution_plan_status(self):
        with tempfile.TemporaryDirectory() as work_dir:
            first = Pipeline(work_dir)
            first._ensure_execution_plan("new project")
            first._set_status("代码评审中")

            restarted = Pipeline(work_dir)
            with patch.object(restarted, "_run_stage_1_requirements") as requirements, \
                    patch.object(restarted, "_run_stage_2_development") as development, \
                    patch.object(restarted, "_run_final_reflection") as reflection:
                restarted.run("new project")

            requirements.assert_not_called()
            development.assert_called_once_with()
            reflection.assert_not_called()

    def test_completed_run_archives_requirements_to_next_numbered_directory(self):
        with tempfile.TemporaryDirectory() as work_dir:
            pipeline = Pipeline(work_dir)
            pipeline._ensure_execution_plan("new project")
            pipeline._set_status("已完成")
            Path(work_dir, "requirements-001").mkdir()

            with patch.object(pipeline, "_run_stage_1_requirements"), \
                    patch.object(pipeline, "_run_stage_2_development"), \
                    patch.object(pipeline, "_run_final_reflection"):
                pipeline.run("new project")

            self.assertTrue(Path(work_dir, "requirements").exists())
            self.assertTrue(Path(work_dir, "requirements-002", "execution_plan.json").is_file())

    def test_final_reflection_only_asks_fact_producers_to_curate_memory(self):
        with tempfile.TemporaryDirectory() as work_dir:
            pipeline = Pipeline(work_dir)
            analyst = MagicMock()
            requirements_reviewer = MagicMock()
            developer = MagicMock()
            code_reviewer = MagicMock()
            pipeline.agents = {
                "需求分析": analyst,
                "需求审查": requirements_reviewer,
                "代码开发": developer,
                "代码验证审查": code_reviewer,
            }

            pipeline._run_final_reflection()

            analyst.send_message.assert_called_once()
            developer.send_message.assert_called_once()
            requirements_reviewer.send_message.assert_not_called()
            code_reviewer.send_message.assert_not_called()

            analyst_prompt = analyst.send_message.call_args.args[0]
            developer_prompt = developer.send_message.call_args.args[0]
            self.assertIn("memory/", analyst_prompt)
            self.assertIn("需求侧事实", analyst_prompt)
            self.assertIn("实现侧事实", developer_prompt)
            self.assertIn(pipeline.user_requirements_file, analyst_prompt)
            self.assertIn(pipeline.develop_report_file, developer_prompt)


if __name__ == "__main__":
    unittest.main()

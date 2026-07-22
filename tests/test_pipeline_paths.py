import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

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

        self.assertEqual(pipeline.work_dir, work_dir)
        self.assertEqual(pipeline.user_requirements_file, os.path.join(work_dir, "user_requirements.md"))
        self.assertEqual(pipeline.develop_report_file, os.path.join(work_dir, "develop_report.md"))
        self.assertEqual(pipeline.test_report_file, os.path.join(work_dir, "test_report.md"))

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
                    patch("pipeline.human_gate", return_value=None), \
                    patch("pipeline.os.mkdir") as mkdir:
                pipeline._run_stage_2_development()

            self.assertEqual(
                created,
                [
                    ("代码开发", "code_developer.md"),
                    ("代码验证审查", "code_reviewer.md"),
                ],
            )
            mkdir.assert_not_called()

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

        with patch("pipeline.Agent") as agent_class:
            created = pipeline._create_agent("需求分析", "requirements_analyst.md")

        self.assertIsNotNone(created)
        agent_class.assert_called_once_with(
            "需求分析",
            "requirements_analyst.md",
            pipeline.work_dir,
            add_dirs=None,
            agent_type="cursor",
        )

    def test_run_passes_user_idea_into_requirements_stage(self):
        pipeline = Pipeline("relative-workspace")

        with patch.object(pipeline, "_run_stage_1_requirements") as requirements, \
                patch.object(pipeline, "_run_stage_2_development") as development, \
                patch.object(pipeline, "_run_final_reflection") as reflection:
            pipeline.run("新增后台管理")

        requirements.assert_called_once_with("新增后台管理")
        development.assert_called_once_with()
        reflection.assert_called_once_with()

    def test_requirements_stage_does_not_create_role_directory(self):
        with tempfile.TemporaryDirectory() as work_dir:
            pipeline = Pipeline(work_dir)
            analyst = MagicMock()
            reviewer = MagicMock()
            reviewer.send_message.return_value = "同意方案"
            agents = {"需求分析": analyst, "需求审查": reviewer}
            created = []

            def create_agent(*args):
                created.append(args)
                return agents[args[0]]

            with patch.object(pipeline, "_create_agent", side_effect=create_agent), \
                    patch("pipeline.human_gate", return_value=None), \
                    patch("pipeline.os.mkdir") as mkdir:
                pipeline._run_stage_1_requirements("new project")

            self.assertEqual(
                created,
                [
                    ("需求分析", "requirements_analyst.md"),
                    ("需求审查", "requirements_reviewer.md"),
                ],
            )
            mkdir.assert_not_called()

    def test_requirement_review_auto_passes_after_three_failed_agent_reviews(self):
        with tempfile.TemporaryDirectory() as work_dir:
            pipeline = Pipeline(work_dir)
            analyst = MagicMock()
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
            gate.assert_called_once_with("1. 需求分析", pipeline.user_requirements_file, skip_human=False)

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

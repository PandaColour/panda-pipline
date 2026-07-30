import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from agents import Agent
from agents._result import AgentRunResult
from break_pipeline import BREAK_SYSTEM_PROMPT_DIR
from break_pipeline import BreakPipeline
from break_pipeline import RequirementItem


class SessionReturningAgent:
    def run(self, work_dir, message, system_prompt=None, session_id=None, add_dirs=None):
        return AgentRunResult("ok", session_id or "restored-session", 0)


class BreakPipelineTests(unittest.TestCase):
    def test_skip_human_is_forwarded_to_break_human_gates(self):
        pipeline = BreakPipeline("workspace", skip_human=True)

        with patch("break_pipeline.human_gate", return_value=None) as gate:
            pipeline._human_gate("测试", "workspace/requirements/index.md")

        gate.assert_called_once_with("测试", "workspace/requirements/index.md", skip_human=True)

    def test_item_artifacts_stay_in_its_own_workspace(self):
        pipeline = BreakPipeline("workspace")
        item = RequirementItem(
            1, "R-001", "login", "待实施", [],
            "R-001-login/user_requirements.md", "ok",
        )

        paths = pipeline._item_paths(item)

        self.assertEqual(paths["requirements"], os.path.join(pipeline.requirements_dir, "R-001-login", "user_requirements.md"))
        self.assertEqual(paths["requirements_analysis"], os.path.join(pipeline.requirements_dir, "R-001-login", "requirements_analysis.md"))
        self.assertEqual(paths["develop"], os.path.join(pipeline.requirements_dir, "R-001-login", "develop_report.md"))
        self.assertEqual(paths["test"], os.path.join(pipeline.requirements_dir, "R-001-login", "test_report.md"))
        self.assertEqual(paths["code_review"], os.path.join(pipeline.requirements_dir, "R-001-login", "code_review.md"))

    def test_item_artifacts_include_memory_report(self):
        pipeline = BreakPipeline("workspace")
        item = RequirementItem(
            1, "R-001", "login", "待实施", [],
            "R-001-login/user_requirements.md", "ok",
        )

        paths = pipeline._item_paths(item)

        self.assertEqual(
            paths["memory_report"],
            os.path.join(pipeline.requirements_dir, "R-001-login", "memory_report.md"),
        )

    def test_memory_status_is_runnable(self):
        pipeline = BreakPipeline("workspace")
        item = RequirementItem(1, "R-001", "login", "记忆整理中", [], "R-001-login/user_requirements.md", "ok")

        self.assertIs(pipeline._next_runnable_item([item]), item)

    def test_same_item_reuses_its_agent_set_for_rework(self):
        pipeline = BreakPipeline("workspace")
        item = RequirementItem(1, "R-001", "login", "待实施", [], "R-001-login/user_requirements.md", "ok")

        with patch.object(pipeline, "_create_agent", side_effect=lambda name, prompt: MagicMock(name=name)) as create_agent:
            first = pipeline._item_agents(item)
            second = pipeline._item_agents(item)

        self.assertIs(first, second)
        self.assertEqual(create_agent.call_count, 4)
        self.assertEqual(set(first), {"analyst", "requirements_reviewer", "developer", "code_reviewer"})

    def test_different_items_get_different_agent_sets(self):
        pipeline = BreakPipeline("workspace")
        first_item = RequirementItem(1, "R-001", "first", "待实施", [], "R-001-first/user_requirements.md", "ok")
        second_item = RequirementItem(2, "R-002", "second", "待实施", [], "R-002-second/user_requirements.md", "ok")

        with patch.object(pipeline, "_create_agent", side_effect=lambda name, prompt: MagicMock(name=name)) as create_agent:
            first = pipeline._item_agents(first_item)
            second = pipeline._item_agents(second_item)

        self.assertIsNot(first, second)
        self.assertEqual(create_agent.call_count, 8)

    def test_memory_completion_releases_current_item_agents(self):
        pipeline = BreakPipeline("workspace")
        agent = MagicMock()
        agent.name = "R-001 小需求开发"
        pipeline._active_item_agents["R-001"] = {"developer": agent}
        pipeline.agents[agent.name] = agent

        pipeline._release_item_agents("R-001")

        self.assertNotIn("R-001", pipeline._active_item_agents)
        self.assertNotIn(agent.name, pipeline.agents)

    def test_memory_curation_template_lives_in_break_system_prompt(self):
        template = Path(BREAK_SYSTEM_PROMPT_DIR) / "memory_curation.md"

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

    def test_item_memory_prompt_renders_break_system_prompt_template(self):
        with tempfile.TemporaryDirectory() as work_dir, tempfile.TemporaryDirectory() as prompt_dir:
            template = Path(prompt_dir) / "memory_curation.md"
            template.write_text(
                "CUSTOM TEMPLATE\n"
                "{opening}\n"
                "{read_instruction}\n"
                "{curation_scope}\n"
                "{execution_plan_file}\n"
                "{closing_instruction}\n",
                encoding="utf-8",
            )
            pipeline = BreakPipeline(work_dir)
            pipeline.prompt_dir = prompt_dir
            self._write_requirement_files(work_dir, "R-001")
            self._write_index(work_dir, [(1, "R-001", "记忆整理中", "无", "001-first.md")])
            item = RequirementItem(
                1, "R-001", "name", "记忆整理中", [],
                "R-001-first/user_requirements.md", "ok",
            )
            agents = self._item_agent_set()

            pipeline._run_item_memory(item, agents)

            analyst_prompt = agents["analyst"].send_message.call_args.args[0]
            developer_prompt = agents["developer"].send_message.call_args.args[0]
            for prompt in (analyst_prompt, developer_prompt):
                self.assertIn("CUSTOM TEMPLATE", prompt)
                self.assertIn(pipeline.execution_plan_file, prompt)
                self.assertIn("调用消息指定的小需求已通过人工审核", prompt)

    def test_code_approval_runs_memory_curation_before_completion(self):
        with tempfile.TemporaryDirectory() as work_dir:
            pipeline = BreakPipeline(work_dir)
            self._write_requirement_files(work_dir, "R-001")
            self._write_index(work_dir, [(1, "R-001", "待实施", "无", "001-first.md")])
            agents = self._item_agent_set()
            agents["code_reviewer"].send_message.return_value = "任务完成"

            with patch.object(pipeline, "_item_agents", return_value=agents), \
                    patch("break_pipeline.human_gate", return_value=None):
                pipeline._run_execution()

            self.assertEqual(agents["analyst"].send_message.call_count, 1)
            agents["requirements_reviewer"].send_message.assert_not_called()
            self.assertEqual(agents["developer"].send_message.call_count, 2)
            self.assertEqual(agents["code_reviewer"].send_message.call_count, 1)
            self.assertIn("需求侧事实", agents["analyst"].send_message.call_args.args[0])
            self.assertIn("memory_report.md", agents["developer"].send_message.call_args.args[0])
            plan = json.loads(Path(pipeline.execution_plan_file).read_text(encoding="utf-8"))
            self.assertEqual(plan["items"][0]["status"], "已完成")

    def test_item_memory_prompt_bans_requirement_ids_from_long_term_memory(self):
        with tempfile.TemporaryDirectory() as work_dir:
            pipeline = BreakPipeline(work_dir)
            self._write_requirement_files(work_dir, "R-001")
            self._write_index(work_dir, [(1, "R-001", "记忆整理中", "无", "001-first.md")])
            item = RequirementItem(
                1, "R-001", "name", "记忆整理中", [],
                "R-001-first/user_requirements.md", "ok",
            )
            agents = self._item_agent_set()

            pipeline._run_item_memory(item, agents)

            analyst_prompt = agents["analyst"].send_message.call_args.args[0]
            developer_prompt = agents["developer"].send_message.call_args.args[0]
            for prompt in (analyst_prompt, developer_prompt):
                self.assertIn("记忆整理目的", prompt)
                self.assertIn("为后续类似项目从0到1提供指导", prompt)
                self.assertIn("为后续需求提供代码索引", prompt)
                self.assertIn("架构边界", prompt)
                self.assertIn("关键类/函数", prompt)
                self.assertIn("当前源码", prompt)
                self.assertIn("execution_plan.json", prompt)
                self.assertIn("当前已实现事实", prompt)
                self.assertIn("长期 memory 不得写入 R-xxx", prompt)
                self.assertIn("不得写入小需求名称", prompt)
                self.assertIn("来源追溯只保留在 memory_report.md 和 execution_plan.json", prompt)
                self.assertIn("不进入 memory/ 文件", prompt)
                self.assertNotIn("只能作为来源证据", prompt)
                self.assertIn("历史 memory", prompt)
                self.assertIn("未沉淀原因", prompt)

    def test_restart_at_memory_status_only_runs_curator(self):
        with tempfile.TemporaryDirectory() as work_dir:
            pipeline = BreakPipeline(work_dir)
            self._write_requirement_files(work_dir, "R-001")
            self._write_index(work_dir, [(1, "R-001", "待记忆整理", "无", "001-first.md")])
            agents = self._item_agent_set()

            with patch.object(pipeline, "_item_agents", return_value=agents):
                pipeline._run_execution()

            agents["analyst"].send_message.assert_called_once()
            agents["developer"].send_message.assert_called_once()
            agents["requirements_reviewer"].send_message.assert_not_called()
            agents["code_reviewer"].send_message.assert_not_called()

    def test_final_reflection_only_calls_breakdown_agent(self):
        with tempfile.TemporaryDirectory() as work_dir:
            pipeline = BreakPipeline(work_dir)
            self._write_requirement_files(work_dir, "R-001")
            self._write_index(work_dir, [(1, "R-001", "已完成", "无", "001-first.md")])
            breakdown_agent = MagicMock()
            pipeline.agents["需求拆分"] = breakdown_agent

            with patch.object(pipeline, "_create_agent", return_value=breakdown_agent) as create_agent:
                pipeline._run_final_reflection()

            create_agent.assert_not_called()
            breakdown_agent.send_message.assert_called_once()

    def test_final_memory_prompt_bans_requirement_ids_from_long_term_memory(self):
        with tempfile.TemporaryDirectory() as work_dir:
            pipeline = BreakPipeline(work_dir)
            self._write_requirement_files(work_dir, "R-001")
            self._write_index(work_dir, [(1, "R-001", "已完成", "无", "001-first.md")])
            breakdown_agent = MagicMock()
            pipeline.agents["需求拆分"] = breakdown_agent

            pipeline._run_final_reflection()

            prompt = breakdown_agent.send_message.call_args.args[0]
            self.assertIn("记忆整理目的", prompt)
            self.assertIn("为后续类似项目从0到1提供指导", prompt)
            self.assertIn("为后续需求提供代码索引", prompt)
            self.assertIn("架构边界", prompt)
            self.assertIn("关键类/函数", prompt)
            self.assertIn("当前源码", prompt)
            self.assertIn("execution_plan.json", prompt)
            self.assertIn("当前已实现事实", prompt)
            self.assertIn("长期 memory 不得写入 R-xxx", prompt)
            self.assertIn("不得写入小需求名称", prompt)
            self.assertIn("来源追溯只保留在 memory_report.md 和 execution_plan.json", prompt)
            self.assertIn("不进入 memory/ 文件", prompt)
            self.assertNotIn("只能作为来源证据", prompt)
            self.assertIn("历史 memory", prompt)
            self.assertIn("按模块、接口、业务规则和架构能力组织", prompt)

    @staticmethod
    def _item_agent_set():
        return {
            "analyst": MagicMock(),
            "requirements_reviewer": MagicMock(),
            "developer": MagicMock(),
            "code_reviewer": MagicMock(),
        }
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

    def test_breakdown_creates_draft_plan_before_agents(self):
        with tempfile.TemporaryDirectory() as work_dir:
            pipeline = BreakPipeline(work_dir)

            def create_agent(name, _prompt):
                self.assertTrue(Path(pipeline.execution_plan_file).exists(), name)
                agent = MagicMock()
                agent.send_message.return_value = "拆分方案通过" if name == "拆分评审" else "ok"
                return agent

            with patch.object(pipeline, "_create_agent", side_effect=create_agent), \
                    patch.object(pipeline, "_human_gate", return_value=None):
                pipeline._run_breakdown("大需求")

            plan = json.loads(Path(pipeline.execution_plan_file).read_text(encoding="utf-8"))
            self.assertEqual(plan["demand"]["source"], "大需求")

    def test_item_agent_session_is_saved_after_send(self):
        with tempfile.TemporaryDirectory() as work_dir:
            pipeline = BreakPipeline(work_dir)
            self._write_requirement_files(work_dir, "R-001")
            self._write_index(work_dir, [(1, "R-001", "待实施", "无", "001-first.md")])
            previous_codex = Agent._STRATEGY_MAP["codex"]
            Agent._STRATEGY_MAP["codex"] = SessionReturningAgent
            try:
                agent = pipeline._create_agent("R-001 小需求开发", "item_developer.md")
                agent.send_message("开发")
            finally:
                Agent._STRATEGY_MAP["codex"] = previous_codex

            plan = json.loads(Path(pipeline.execution_plan_file).read_text(encoding="utf-8"))
            self.assertEqual(
                plan["items"][0]["agent_sessions"]["R-001 小需求开发"]["session_id"],
                "restored-session",
            )

    def test_item_agent_session_backend_mismatch_starts_fresh(self):
        with tempfile.TemporaryDirectory() as work_dir:
            pipeline = BreakPipeline(work_dir)
            self._write_requirement_files(work_dir, "R-001")
            self._write_index(work_dir, [(1, "R-001", "待实施", "无", "001-first.md")])
            plan = json.loads(Path(pipeline.execution_plan_file).read_text(encoding="utf-8"))
            plan["items"][0]["agent_sessions"] = {
                "R-001 小需求开发": {
                    "session_id": "saved-session",
                    "agent_type": "cursor",
                    "prompt_file": "item_developer.md",
                }
            }
            Path(pipeline.execution_plan_file).write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")

            previous_codex = Agent._STRATEGY_MAP["codex"]
            Agent._STRATEGY_MAP["codex"] = SessionReturningAgent
            try:
                restarted = BreakPipeline(work_dir)
                agent = restarted._create_agent("R-001 小需求开发", "item_developer.md")
                self.assertIsNone(agent.session_id)
                agent.send_message("开发")
            finally:
                Agent._STRATEGY_MAP["codex"] = previous_codex

            self.assertEqual(agent.session_id, "restored-session")
            plan = json.loads(Path(restarted.execution_plan_file).read_text(encoding="utf-8"))
            session = plan["items"][0]["agent_sessions"]["R-001 小需求开发"]
            self.assertEqual(session["session_id"], "restored-session")
            self.assertEqual(session["agent_type"], "codex")

    def test_item_agent_session_matching_backend_is_restored(self):
        with tempfile.TemporaryDirectory() as work_dir:
            pipeline = BreakPipeline(work_dir)
            self._write_requirement_files(work_dir, "R-001")
            self._write_index(work_dir, [(1, "R-001", "待实施", "无", "001-first.md")])
            plan = json.loads(Path(pipeline.execution_plan_file).read_text(encoding="utf-8"))
            plan["items"][0]["agent_sessions"] = {
                "R-001 小需求开发": {
                    "session_id": "saved-session",
                    "agent_type": "codex",
                    "prompt_file": "item_developer.md",
                }
            }
            Path(pipeline.execution_plan_file).write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")

            restarted = BreakPipeline(work_dir)
            agent = restarted._create_agent("R-001 小需求开发", "item_developer.md")

            self.assertEqual(agent.session_id, "saved-session")

    def test_item_agent_legacy_session_without_backend_is_restored(self):
        with tempfile.TemporaryDirectory() as work_dir:
            pipeline = BreakPipeline(work_dir)
            self._write_requirement_files(work_dir, "R-001")
            self._write_index(work_dir, [(1, "R-001", "待实施", "无", "001-first.md")])
            plan = json.loads(Path(pipeline.execution_plan_file).read_text(encoding="utf-8"))
            plan["items"][0]["agent_sessions"] = {
                "R-001 小需求开发": {
                    "session_id": "legacy-session",
                    "prompt_file": "item_developer.md",
                }
            }
            Path(pipeline.execution_plan_file).write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")

            restarted = BreakPipeline(work_dir)
            agent = restarted._create_agent("R-001 小需求开发", "item_developer.md")

            self.assertEqual(agent.session_id, "legacy-session")

    def test_item_agent_legacy_string_session_is_restored(self):
        with tempfile.TemporaryDirectory() as work_dir:
            pipeline = BreakPipeline(work_dir)
            self._write_requirement_files(work_dir, "R-001")
            self._write_index(work_dir, [(1, "R-001", "待实施", "无", "001-first.md")])
            plan = json.loads(Path(pipeline.execution_plan_file).read_text(encoding="utf-8"))
            plan["items"][0]["agent_sessions"] = {
                "R-001 小需求开发": "legacy-string-session",
            }
            Path(pipeline.execution_plan_file).write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")

            restarted = BreakPipeline(work_dir)
            agent = restarted._create_agent("R-001 小需求开发", "item_developer.md")

            self.assertEqual(agent.session_id, "legacy-string-session")

    def test_demand_agent_session_is_saved_and_restored(self):
        with tempfile.TemporaryDirectory() as work_dir:
            pipeline = BreakPipeline(work_dir)
            self._write_requirement_files(work_dir, "R-001")
            self._write_index(work_dir, [(1, "R-001", "待实施", "无", "001-first.md")])
            pipeline._set_demand_status("拆分中", source="大需求")
            previous_codex = Agent._STRATEGY_MAP["codex"]
            Agent._STRATEGY_MAP["codex"] = SessionReturningAgent
            try:
                agent = pipeline._create_agent("需求拆分", "requirement_breaker.md")
                agent.send_message("拆分")
            finally:
                Agent._STRATEGY_MAP["codex"] = previous_codex

            plan = json.loads(Path(pipeline.execution_plan_file).read_text(encoding="utf-8"))
            self.assertEqual(plan["demand"]["agent_sessions"]["需求拆分"]["session_id"], "restored-session")

            restarted = BreakPipeline(work_dir)
            restored = restarted._create_agent("需求拆分", "requirement_breaker.md")
            self.assertEqual(restored.session_id, "restored-session")

    def test_breakdown_resource_blocker_forces_human_gate_before_review(self):
        blocked = (
            "FINAL_ANSWER\n```json\n"
            '{"status":"blocked","approval_token":"","summary":"无法读取设计文件",'
            '"blocker":{"kind":"file_unreadable","resource":"/tmp/design.fig",'
            '"reason":"permission denied","required_user_action":"授予读取权限"}}\n```'
        )
        with tempfile.TemporaryDirectory() as work_dir:
            pipeline = BreakPipeline(work_dir, skip_human=True)
            breaker = MagicMock()
            breaker.send_message.side_effect = [blocked, "拆分已更新"]
            reviewer = MagicMock()
            reviewer.send_message.return_value = "拆分方案通过"

            def human_gate_response(stage_name, _review_file_path, skip_human):
                if "资源访问阻塞" in stage_name:
                    self.assertFalse(skip_human)
                    return "已授予读取权限"
                self.assertTrue(skip_human)
                return None

            with patch.object(pipeline, "_create_agent", side_effect=[breaker, reviewer]), \
                    patch("break_pipeline.human_gate", side_effect=human_gate_response) as gate, \
                    patch("builtins.print") as output:
                pipeline._run_breakdown("大需求")

        gate.assert_any_call(
            "1. 大需求拆分资源访问阻塞：无法读取设计文件",
            pipeline.requirements_index_file,
            skip_human=False,
        )
        self.assertIn("已授予读取权限", breaker.send_message.call_args_list[1].args[0])
        reviewer.send_message.assert_called_once()
        printed = "\n".join(str(call.args[0]) for call in output.call_args_list if call.args)
        self.assertIn("/tmp/design.fig", printed)
        self.assertIn("permission denied", printed)
        self.assertIn("授予读取权限", printed)

    def test_breakdown_gate_ignores_unrelated_blocked_result(self):
        response = (
            "FINAL_ANSWER\n```json\n"
            '{"status":"blocked","approval_token":"","summary":"等待产品决策",'
            '"blocker":{"kind":"product_decision"}}\n```'
        )

        self.assertIsNone(BreakPipeline._breakdown_resource_blocker(response))

    def test_breakdown_gate_ignores_unmarked_blocked_json(self):
        response = (
            "拆分过程记录：\n```json\n"
            '{"status":"blocked","approval_token":"","summary":"无法读取设计文件",'
            '"blocker":{"kind":"file_unreadable"}}\n```'
        )

        self.assertIsNone(BreakPipeline._breakdown_resource_blocker(response))

    def test_breakdown_gate_ignores_incomplete_resource_blocker(self):
        response = (
            "FINAL_ANSWER\n```json\n"
            '{"status":"blocked","approval_token":"","summary":"无法读取设计文件",'
            '"blocker":{"kind":"file_unreadable","resource":"/tmp/design.fig"}}\n```'
        )

        self.assertIsNone(BreakPipeline._breakdown_resource_blocker(response))

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

    def test_breakdown_review_auto_passes_after_three_failed_agent_reviews(self):
        with tempfile.TemporaryDirectory() as work_dir:
            pipeline = BreakPipeline(work_dir)
            breaker = MagicMock()
            reviewer = MagicMock()
            reviewer.send_message.side_effect = ["缺少验收标准", "拆分粒度过大", "仍有阻塞风险"]

            with patch.object(pipeline, "_create_agent", side_effect=[breaker, reviewer]), \
                    patch("builtins.input", return_value="大需求"), \
                    patch("break_pipeline.human_gate", return_value=None) as gate:
                pipeline._run_breakdown()

        self.assertEqual(reviewer.send_message.call_count, 3)
        self.assertEqual(breaker.send_message.call_count, 3)
        gate.assert_called_once()

    def test_existing_index_receives_supplemental_breakdown_instruction(self):
        with tempfile.TemporaryDirectory() as work_dir:
            pipeline = BreakPipeline(work_dir)
            Path(pipeline.requirements_dir).mkdir()
            Path(pipeline.requirements_index_file).write_text("existing", encoding="utf-8")
            breaker = MagicMock()
            reviewer = MagicMock()
            reviewer.send_message.return_value = "拆分方案通过"

            with patch.object(pipeline, "_create_agent", side_effect=[breaker, reviewer]), \
                    patch("break_pipeline.human_gate", return_value=None):
                pipeline._run_breakdown("补充支付失败场景")

        breaker.send_message.assert_called_once()
        prompt = breaker.send_message.call_args.args[0]
        self.assertIn("补充支付失败场景", prompt)
        self.assertIn("保留", prompt)

    def test_breakdown_instruction_requires_global_context_in_each_item(self):
        pipeline = BreakPipeline("workspace")

        prompt = pipeline._breakdown_instruction("客户要做登录；测试账号 alice，密码 secret")

        self.assertIn("全局上下文", prompt)
        self.assertIn("每个小需求", prompt)
        self.assertIn("测试环境、账号、密码", prompt)
        self.assertIn("原始需求", prompt)

    def test_empty_review_response_is_treated_as_approval(self):
        with tempfile.TemporaryDirectory() as work_dir:
            pipeline = BreakPipeline(work_dir)
            breaker = MagicMock()
            reviewer = MagicMock()
            reviewer.send_message.return_value = ""

            with patch.object(pipeline, "_create_agent", side_effect=[breaker, reviewer]), \
                    patch("builtins.input", return_value="大需求"), \
                    patch("break_pipeline.human_gate", return_value=None) as gate:
                pipeline._run_breakdown()

        gate.assert_called_once()

    def test_review_approval_supports_structured_final_answer(self):
        response = (
            "I'll re-read the files first.\n"
            "FINAL_ANSWER\n"
            "```json\n"
            '{"status":"approved","approval_token":"拆分方案通过","summary":"ok","issues":[]}\n'
            "```"
        )

        self.assertTrue(BreakPipeline._review_passed(response, "拆分方案通过"))

    def test_review_rejection_json_wins_over_legacy_token_text(self):
        response = (
            "FINAL_ANSWER\n"
            "```json\n"
            '{"status":"changes_requested","approval_token":"","summary":"不要判成拆分方案通过","issues":[]}\n'
            "```"
        )

        self.assertFalse(BreakPipeline._review_passed(response, "拆分方案通过"))

    def test_review_approval_keeps_legacy_token_compatibility(self):
        self.assertTrue(BreakPipeline._review_passed("提示：请继续。拆分方案通过", "拆分方案通过"))

    def test_requirement_change_supports_structured_final_answer(self):
        response = (
            "FINAL_ANSWER\n"
            "```json\n"
            '{"status":"requirement_change","approval_token":"","summary":"需求变更: 补充失败场景","issues":[]}\n'
            "```"
        )

        self.assertTrue(BreakPipeline._is_requirement_change(response))

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

            plan = json.loads(Path(pipeline.execution_plan_file).read_text(encoding="utf-8"))
            self.assertEqual(plan["items"][1]["status"], "阻塞")

    def test_only_blocked_dependency_chain_ends_execution_without_error(self):
        with tempfile.TemporaryDirectory() as work_dir:
            pipeline = BreakPipeline(work_dir)
            self._write_requirement_files(work_dir, "R-001", "R-002", "R-003")
            self._write_index(work_dir, [
                (1, "R-001", "已完成", "无", "001-first.md"),
                (2, "R-002", "阻塞", "R-001", "002-second.md"),
                (3, "R-003", "待需求分析", "R-002", "R-003-second/user_requirements.md"),
            ])

            completed = pipeline._run_execution()

        self.assertFalse(completed)

    def test_blocked_execution_does_not_run_final_reflection(self):
        with tempfile.TemporaryDirectory() as work_dir:
            pipeline = BreakPipeline(work_dir)
            Path(pipeline.requirements_dir).mkdir()
            Path(pipeline.breakdown_approval_file).write_text("approved\n", encoding="utf-8")

            with patch.object(pipeline, "_run_execution", return_value=False), \
                    patch.object(pipeline, "_run_final_reflection") as reflection:
                pipeline.run()

        reflection.assert_not_called()

    def test_run_with_new_user_input_reruns_breakdown_even_after_approval(self):
        with tempfile.TemporaryDirectory() as work_dir:
            pipeline = BreakPipeline(work_dir)
            Path(pipeline.requirements_dir).mkdir()
            Path(pipeline.requirements_index_file).write_text("existing", encoding="utf-8")
            Path(pipeline.breakdown_approval_file).write_text("approved\n", encoding="utf-8")
            with patch.object(pipeline, "_run_breakdown") as breakdown, \
                    patch.object(pipeline, "_run_execution", return_value=True) as execution, \
                    patch.object(pipeline, "_run_final_reflection"):
                pipeline.run("补充需求")

        breakdown.assert_called_once_with("补充需求")
        execution.assert_called_once_with()

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
            with self.assertRaisesRegex(ValueError, "缺少需求索引"):
                pipeline._load_items()

    def test_execution_creates_reports_directory(self):
        with tempfile.TemporaryDirectory() as work_dir:
            pipeline = BreakPipeline(work_dir)
            workspace = Path(work_dir) / "requirements" / "R-001-first"
            workspace.mkdir(parents=True)
            (workspace / "user_requirements.md").write_text("# R-001\n", encoding="utf-8")
            self._write_index(work_dir, [(1, "R-001", "待实施", "无", "R-001-first/user_requirements.md")])
            agents = self._item_agent_set()
            agents["code_reviewer"].send_message.return_value = "任务完成"
            with patch.object(pipeline, "_item_agents", return_value=agents), \
                    patch("break_pipeline.human_gate", return_value=None):
                pipeline._run_execution()

            self.assertTrue(workspace.is_dir())

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

    def test_completed_run_archives_requirements_to_next_numbered_directory(self):
        with tempfile.TemporaryDirectory() as work_dir:
            pipeline = BreakPipeline(work_dir)
            self._write_requirement_files(work_dir, "R-001")
            self._write_index(work_dir, [(1, "R-001", "已完成", "无", "001-first.md")])
            Path(work_dir, "requirements-001").mkdir()
            Path(pipeline.breakdown_approval_file).write_text("approved\n", encoding="utf-8")

            with patch.object(pipeline, "_run_final_reflection"):
                pipeline.run()

            self.assertFalse(Path(work_dir, "requirements").exists())
            self.assertTrue(Path(work_dir, "requirements-002", "index.md").is_file())

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
            workspace = Path(work_dir) / "requirements" / "R-001-first"
            workspace.mkdir(parents=True)
            (workspace / "user_requirements.md").write_text("# R-001\n", encoding="utf-8")
            self._write_index(work_dir, [(1, "R-001", "待实施", "无", "R-001-first/user_requirements.md")])
            agents = self._item_agent_set()
            agents["code_reviewer"].send_message.return_value = "任务完成"
            with patch.object(pipeline, "_item_agents", return_value=agents), \
                    patch("break_pipeline.human_gate", return_value=None):
                pipeline._run_execution()

            self.assertIn(str(workspace / "code_review.md"), agents["code_reviewer"].send_message.call_args.args[0])

    def test_waiting_human_item_resumes_at_human_gate(self):
        with tempfile.TemporaryDirectory() as work_dir:
            pipeline = BreakPipeline(work_dir)
            self._write_requirement_files(work_dir, "R-001")
            self._write_index(work_dir, [(1, "R-001", "待人工确认", "无", "001-first.md")])
            agents = self._item_agent_set()
            with patch.object(pipeline, "_item_agents", return_value=agents), \
                    patch("break_pipeline.human_gate", return_value=None):
                pipeline._run_execution()

            self.assertEqual(agents["developer"].send_message.call_count, 1)
            self.assertIn("memory_report.md", agents["developer"].send_message.call_args.args[0])
            plan = json.loads(Path(pipeline.execution_plan_file).read_text(encoding="utf-8"))
            self.assertEqual(plan["items"][0]["status"], "已完成")

    def test_restart_at_code_review_runs_reviewer_without_rerunning_developer(self):
        with tempfile.TemporaryDirectory() as work_dir:
            pipeline = BreakPipeline(work_dir)
            self._write_requirement_files(work_dir, "R-001")
            self._write_index(work_dir, [(1, "R-001", "代码评审中", "无", "001-first.md")])
            agents = self._item_agent_set()
            agents["code_reviewer"].send_message.return_value = "任务完成"

            with patch.object(pipeline, "_item_agents", return_value=agents), \
                    patch("break_pipeline.human_gate", return_value=None):
                pipeline._run_execution()

            self.assertEqual(agents["code_reviewer"].send_message.call_count, 1)
            self.assertEqual(agents["developer"].send_message.call_count, 1)
            self.assertIn("memory_report.md", agents["developer"].send_message.call_args.args[0])
            self.assertNotIn("只实现当前需求", agents["developer"].send_message.call_args.args[0])

    def test_pending_human_feedback_survives_pipeline_restart(self):
        with tempfile.TemporaryDirectory() as work_dir:
            pipeline = BreakPipeline(work_dir)
            self._write_requirement_files(work_dir, "R-001")
            self._write_index(work_dir, [(1, "R-001", "待人工确认", "无", "001-first.md")])

            with patch("break_pipeline.human_gate", return_value="修正 R-001"):
                pipeline._resume_human_gate(pipeline._load_items()[0])

            saved_plan = json.loads(Path(pipeline.execution_plan_file).read_text(encoding="utf-8"))
            self.assertEqual(saved_plan["items"][0]["status"], "开发中")
            self.assertEqual(saved_plan["items"][0]["pending_feedback"]["message"], "修正 R-001")

            restarted = BreakPipeline(work_dir)
            agents = self._item_agent_set()
            agents["code_reviewer"].send_message.return_value = "任务完成"

            with patch.object(restarted, "_item_agents", return_value=agents), \
                    patch("break_pipeline.human_gate", return_value=None):
                restarted._run_execution()

            self.assertIn("修正 R-001", agents["developer"].send_message.call_args_list[0].args[0])
            saved_plan = json.loads(Path(restarted.execution_plan_file).read_text(encoding="utf-8"))
            self.assertIsNone(saved_plan["items"][0]["pending_feedback"])

    def test_item_requirement_gates_run_before_development(self):
        with tempfile.TemporaryDirectory() as work_dir:
            pipeline = BreakPipeline(work_dir)
            self._write_requirement_files(work_dir, "R-001")
            self._write_index(work_dir, [(1, "R-001", "待需求分析", "无", "001-first.md")])
            agents = self._item_agent_set()
            agents["requirements_reviewer"].send_message.return_value = "同意方案"
            agents["code_reviewer"].send_message.return_value = "任务完成"
            with patch.object(pipeline, "_item_agents", return_value=agents), \
                    patch("break_pipeline.human_gate", side_effect=[None, None]):
                pipeline._run_execution()

            self.assertEqual(agents["analyst"].send_message.call_count, 2)
            self.assertEqual(agents["requirements_reviewer"].send_message.call_count, 1)
            self.assertEqual(agents["developer"].send_message.call_count, 2)
            plan = json.loads(Path(pipeline.execution_plan_file).read_text(encoding="utf-8"))
            self.assertEqual(plan["items"][0]["status"], "已完成")

    def test_item_requirement_review_feedback_retries_only_current_analyst(self):
        with tempfile.TemporaryDirectory() as work_dir:
            pipeline = BreakPipeline(work_dir)
            self._write_requirement_files(work_dir, "R-001")
            self._write_index(work_dir, [(1, "R-001", "待需求分析", "无", "001-first.md")])
            agents = self._item_agent_set()
            agents["requirements_reviewer"].send_message.side_effect = ["补充异常场景", "同意方案", None]
            agents["code_reviewer"].send_message.return_value = "任务完成"
            with patch.object(pipeline, "_item_agents", return_value=agents), \
                    patch("break_pipeline.human_gate", side_effect=[None, None]):
                pipeline._run_execution()

            self.assertEqual(agents["analyst"].send_message.call_count, 3)
            self.assertIn("补充异常场景", agents["analyst"].send_message.call_args_list[1].args[0])

    def test_item_requirement_review_auto_passes_after_three_failed_agent_reviews(self):
        with tempfile.TemporaryDirectory() as work_dir:
            pipeline = BreakPipeline(work_dir)
            self._write_requirement_files(work_dir, "R-001")
            self._write_index(work_dir, [(1, "R-001", "待需求分析", "无", "001-first.md")])
            item = pipeline._load_items()[0]
            analyst = MagicMock()
            reviewer = MagicMock()
            reviewer.send_message.side_effect = ["缺少边界", "缺少异常", "缺少验收"]

            with patch("break_pipeline.human_gate", return_value=None):
                pipeline._run_item_requirements(item, analyst, reviewer)

            self.assertEqual(reviewer.send_message.call_count, 3)
            self.assertEqual(analyst.send_message.call_count, 3)
            self.assertIn("缺少边界", analyst.send_message.call_args_list[1].args[0])
            self.assertIn("缺少异常", analyst.send_message.call_args_list[2].args[0])
            plan = json.loads(Path(pipeline.execution_plan_file).read_text(encoding="utf-8"))
            self.assertEqual(plan["items"][0]["status"], "待开发")

    def test_requirement_change_from_code_review_returns_to_requirement_gates(self):
        with tempfile.TemporaryDirectory() as work_dir:
            pipeline = BreakPipeline(work_dir)
            self._write_requirement_files(work_dir, "R-001")
            self._write_index(work_dir, [(1, "R-001", "待实施", "无", "001-first.md")])
            agents = self._item_agent_set()
            agents["requirements_reviewer"].send_message.return_value = "同意方案"
            agents["code_reviewer"].send_message.side_effect = ["需求变更: 补充失败场景", "任务完成", None]
            with patch.object(pipeline, "_item_agents", return_value=agents), \
                    patch("break_pipeline.human_gate", side_effect=[None, None]):
                pipeline._run_execution()

            self.assertEqual(agents["analyst"].send_message.call_count, 2)
            self.assertEqual(agents["developer"].send_message.call_count, 3)

    def test_human_feedback_retries_only_current_item(self):
        with tempfile.TemporaryDirectory() as work_dir:
            pipeline = BreakPipeline(work_dir)
            self._write_requirement_files(work_dir, "R-001", "R-002")
            self._write_index(work_dir, [
                (1, "R-001", "待实施", "无", "001-first.md"),
                (2, "R-002", "待实施", "R-001", "002-second.md"),
            ])
            agents = self._item_agent_set()
            agents["code_reviewer"].send_message.return_value = "任务完成"
            with patch.object(pipeline, "_item_agents", return_value=agents), \
                    patch("break_pipeline.human_gate", side_effect=["修正 R-001", None, None]):
                pipeline._run_execution()

        self.assertEqual(agents["developer"].send_message.call_count, 5)
        retry_prompt = agents["developer"].send_message.call_args_list[1].args[0]
        self.assertIn("R-001", retry_prompt)
        self.assertNotIn("R-002", retry_prompt)

    @staticmethod
    def _write_requirement_files(work_dir, *ids):
        folder = Path(work_dir) / "requirements"
        folder.mkdir()
        for number, requirement_id in enumerate(ids, 1):
            workspace = folder / f"R-{number:03d}-{'first' if number == 1 else 'second'}"
            workspace.mkdir()
            (workspace / "user_requirements.md").write_text(
                f"# {requirement_id}\n", encoding="utf-8"
            )

    @staticmethod
    def _write_index(work_dir, rows):
        lines = [
            "| 顺序 | ID | 名称 | 状态 | 前置依赖 | 文件 | 验收摘要 |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
        for order, requirement_id, status, dependencies, filename in rows:
            if filename in {"001-first.md", "002-second.md"}:
                filename = f"R-{order:03d}-{'first' if order == 1 else 'second'}/user_requirements.md"
            lines.append(
                f"| {order} | {requirement_id} | name | {status} | {dependencies} | {filename} | ok |"
            )
        requirements_dir = Path(work_dir) / "requirements"
        index_file = requirements_dir / "index.md"
        index_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
        items = []
        for order, requirement_id, status, dependencies, filename in rows:
            if filename in {"001-first.md", "002-second.md"}:
                filename = f"R-{order:03d}-{'first' if order == 1 else 'second'}/user_requirements.md"
            items.append({
                "order": order,
                "id": requirement_id,
                "name": "name",
                "status": status,
                "dependencies": [] if dependencies in {"无", "-", ""} else dependencies.split(","),
                "requirements_file": filename,
                "acceptance_summary": "ok",
            })
        (requirements_dir / "execution_plan.json").write_text(json.dumps({
            "schema_version": 1,
            "source_index_sha256": hashlib.sha256(index_file.read_bytes()).hexdigest(),
            "items": items,
        }, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()

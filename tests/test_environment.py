import os
import tempfile
import unittest
from unittest.mock import patch

import break_main
import environment
import main


class EnvironmentModuleTests(unittest.TestCase):
    def test_entry_points_use_the_independent_environment_module(self):
        self.assertIs(break_main.setup_environment, environment.setup_environment)
        self.assertIs(main.setup_environment, environment.setup_environment)

    def test_setup_environment_copies_default_memory_into_target_repo(self):
        with tempfile.TemporaryDirectory() as project_root, \
                tempfile.TemporaryDirectory() as source_dir:
            repo_url = "http://example.test/group/lending-app.git"
            target_path = os.path.join(project_root, "lending-app")
            source_file_path = os.path.join(source_dir, "baseline.md")
            with open(source_file_path, "w", encoding="utf-8") as source_file:
                source_file.write("default baseline\n")

            def clone_or_pull(_repo_url, _branch, cloned_path):
                os.makedirs(cloned_path, exist_ok=True)

            with patch.object(environment, "PROJECT_ROOT", project_root), \
                    patch.object(environment, "REPOS", [(repo_url, "main")]), \
                    patch.object(environment, "DEFAULT_MEMORY_SOURCE_DIR", source_dir), \
                    patch.object(environment, "_install_static_analysis_tools"), \
                    patch.object(environment, "_prepare_codegraph") as prepare_codegraph, \
                    patch.object(environment, "_clone_or_pull", side_effect=clone_or_pull):
                work_dir = environment.setup_environment()

            prepare_codegraph.assert_called_once_with(target_path)

            copied_file_path = os.path.join(work_dir, "memory", "baseline.md")
            memory_index_path = os.path.join(work_dir, "memory", "memory_index.md")

            self.assertEqual(work_dir, target_path)
            with open(copied_file_path, encoding="utf-8") as copied_file:
                self.assertEqual(copied_file.read(), "default baseline\n")
            with open(memory_index_path, encoding="utf-8") as index_file:
                memory_index = index_file.read()
            self.assertIn("baseline.md", memory_index)

    def test_setup_environment_prepares_codegraph_for_resolved_work_dir(self):
        with tempfile.TemporaryDirectory() as project_root:
            repo_url = "http://example.test/group/lending-app.git"
            target_path = os.path.join(project_root, "lending-app")

            with patch.object(environment, "PROJECT_ROOT", project_root), \
                    patch.object(environment, "REPOS", [(repo_url, "main")]), \
                    patch.object(environment, "_install_static_analysis_tools"), \
                    patch.object(environment, "_clone_or_pull"), \
                    patch.object(environment, "_prepare_codegraph") as prepare_codegraph, \
                    patch.object(environment, "_ensure_default_memory"):
                work_dir = environment.setup_environment()

            self.assertEqual(work_dir, target_path)
            prepare_codegraph.assert_called_once_with(target_path)

    def test_default_memory_is_not_overwritten_when_present(self):
        with tempfile.TemporaryDirectory() as source_dir, tempfile.TemporaryDirectory() as work_dir:
            source_path = os.path.join(source_dir, "guidelines.md")
            with open(source_path, "w", encoding="utf-8") as source_file:
                source_file.write("default memory\n")

            memory_dir = os.path.join(work_dir, "memory")
            os.makedirs(memory_dir)
            default_memory_path = os.path.join(memory_dir, "guidelines.md")
            with open(default_memory_path, "w", encoding="utf-8") as memory_file:
                memory_file.write("project-specific memory\n")

            with patch.object(environment, "DEFAULT_MEMORY_SOURCE_DIR", source_dir):
                environment._ensure_default_memory(work_dir)

            with open(default_memory_path, encoding="utf-8") as memory_file:
                self.assertEqual(memory_file.read(), "project-specific memory\n")

    def test_default_memory_files_are_copied_and_indexed(self):
        with tempfile.TemporaryDirectory() as source_dir, tempfile.TemporaryDirectory() as work_dir:
            extra_memory_path = os.path.join(source_dir, "kyc_default.md")
            with open(extra_memory_path, "w", encoding="utf-8") as extra_file:
                extra_file.write("# KYC default\n")
            os.makedirs(os.path.join(source_dir, "Compliance"))
            with open(os.path.join(source_dir, "Compliance", "branching.md"), "w", encoding="utf-8") as branch_file:
                branch_file.write("# Compliance branching\n")

            with patch.object(environment, "DEFAULT_MEMORY_SOURCE_DIR", source_dir):
                environment._ensure_default_memory(work_dir)

            self.assertTrue(os.path.isfile(os.path.join(work_dir, "memory", "kyc_default.md")))
            self.assertTrue(os.path.isfile(os.path.join(work_dir, "memory", "Compliance", "branching.md")))
            with open(os.path.join(work_dir, "memory", "memory_index.md"), encoding="utf-8") as index_file:
                memory_index = index_file.read()
            self.assertIn("kyc_default.md", memory_index)
            self.assertIn("Compliance/", memory_index)

    def test_static_analysis_tools_skip_install_when_present(self):
        with patch.object(environment.shutil, "which", return_value="/opt/homebrew/bin/tool"):
            environment._install_static_analysis_tools()

    def test_static_analysis_tools_raise_without_homebrew_when_missing(self):
        with patch.object(environment.shutil, "which", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "Homebrew"):
                environment._install_static_analysis_tools()

    def test_static_analysis_tools_install_missing_via_homebrew(self):
        def which(command):
            return "/opt/homebrew/bin/brew" if command == "brew" else None

        with patch.object(environment.shutil, "which", side_effect=which), \
                patch.object(environment.subprocess, "run") as run:
            environment._install_static_analysis_tools()

        run.assert_called_once_with(
            ["brew", "install", "detekt", "pmd", "checkstyle", "ruff", "swiftlint"],
            check=True,
        )

    def test_codegraph_cli_is_reused_when_already_installed(self):
        with patch.object(
            environment.shutil,
            "which",
            return_value="/usr/local/bin/codegraph",
        ), patch.object(environment.subprocess, "run") as run:
            command = environment._ensure_codegraph_cli()

        self.assertEqual(command, "/usr/local/bin/codegraph")
        run.assert_not_called()

    def test_codegraph_cli_is_installed_globally_with_npm_when_missing(self):
        def which(command):
            if command == "npm":
                return "/usr/local/bin/npm"
            if command == "codegraph" and which.install_finished:
                return "/usr/local/bin/codegraph"
            return None

        which.install_finished = False

        def run(command, **kwargs):
            self.assertEqual(
                command,
                ["/usr/local/bin/npm", "install", "-g", "@colbymchenry/codegraph"],
            )
            self.assertEqual(kwargs, {"check": True})
            which.install_finished = True

        with patch.object(environment.shutil, "which", side_effect=which), \
                patch.object(environment.subprocess, "run", side_effect=run):
            command = environment._ensure_codegraph_cli()

        self.assertEqual(command, "/usr/local/bin/codegraph")

    def test_codegraph_cli_install_failure_warns_and_continues(self):
        def which(command):
            return "/usr/local/bin/npm" if command == "npm" else None

        with patch.object(environment.shutil, "which", side_effect=which), \
                patch.object(
                    environment.subprocess,
                    "run",
                    side_effect=OSError("network unavailable"),
                ), patch("builtins.print") as print_message:
            command = environment._ensure_codegraph_cli()

        self.assertIsNone(command)
        self.assertIn("CodeGraph 安装失败", print_message.call_args.args[0])

    def test_codegraph_init_is_skipped_for_empty_work_dir(self):
        with tempfile.TemporaryDirectory() as work_dir, \
                patch.object(
                    environment,
                    "_ensure_codegraph_cli",
                    return_value="/usr/local/bin/codegraph",
                ), patch.object(environment.subprocess, "run") as run, \
                patch("builtins.print") as print_message:
            environment._prepare_codegraph(work_dir)

        run.assert_not_called()
        self.assertIn("工作目录为空", print_message.call_args.args[0])

    def test_codegraph_initializes_non_empty_project_and_checks_status(self):
        with tempfile.TemporaryDirectory() as work_dir:
            with open(os.path.join(work_dir, "main.py"), "w", encoding="utf-8") as source_file:
                source_file.write("print('ready')\n")

            with patch.object(
                environment,
                "_ensure_codegraph_cli",
                return_value="/usr/local/bin/codegraph",
            ), patch.object(environment.subprocess, "run") as run:
                environment._prepare_codegraph(work_dir)

        self.assertEqual(run.call_args_list, [
            unittest.mock.call(
                ["/usr/local/bin/codegraph", "init", work_dir],
                check=True,
            ),
            unittest.mock.call(
                ["/usr/local/bin/codegraph", "status", work_dir],
                check=True,
            ),
        ])

    def test_codegraph_syncs_existing_index_and_checks_status(self):
        with tempfile.TemporaryDirectory() as work_dir:
            os.makedirs(os.path.join(work_dir, ".codegraph"))

            with patch.object(
                environment,
                "_ensure_codegraph_cli",
                return_value="/usr/local/bin/codegraph",
            ), patch.object(environment.subprocess, "run") as run:
                environment._prepare_codegraph(work_dir)

        self.assertEqual(run.call_args_list, [
            unittest.mock.call(
                ["/usr/local/bin/codegraph", "sync", work_dir],
                check=True,
            ),
            unittest.mock.call(
                ["/usr/local/bin/codegraph", "status", work_dir],
                check=True,
            ),
        ])

    def test_codegraph_initialization_failure_warns_and_continues(self):
        with tempfile.TemporaryDirectory() as work_dir:
            with open(os.path.join(work_dir, "main.py"), "w", encoding="utf-8") as source_file:
                source_file.write("print('ready')\n")

            with patch.object(
                environment,
                "_ensure_codegraph_cli",
                return_value="/usr/local/bin/codegraph",
            ), patch.object(
                environment.subprocess,
                "run",
                side_effect=OSError("index unavailable"),
            ), patch("builtins.print") as print_message:
                environment._prepare_codegraph(work_dir)

        self.assertIn("CodeGraph 准备失败", print_message.call_args.args[0])


if __name__ == "__main__":
    unittest.main()

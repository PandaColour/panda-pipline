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

    def test_setup_environment_initializes_default_loan_memory_in_target_repo(self):
        with tempfile.TemporaryDirectory() as project_root:
            repo_url = "http://example.test/group/lending-app.git"
            target_path = os.path.join(project_root, "lending-app")

            def clone_or_pull(_repo_url, _branch, cloned_path):
                os.makedirs(cloned_path, exist_ok=True)

            with patch.object(environment, "PROJECT_ROOT", project_root), \
                    patch.object(environment, "REPOS", [(repo_url, "main")]), \
                    patch.object(environment, "_clone_or_pull", side_effect=clone_or_pull):
                work_dir = environment.setup_environment()

            default_memory_path = os.path.join(work_dir, "memory", "loan_pipeline_default.md")
            network_demo_path = os.path.join(work_dir, "memory", "Network", "NetworkClient.swift")
            memory_index_path = os.path.join(work_dir, "memory", "memory_index.md")

            self.assertEqual(work_dir, target_path)
            self.assertTrue(os.path.isfile(default_memory_path))
            self.assertTrue(os.path.isfile(network_demo_path))
            with open(default_memory_path, encoding="utf-8") as memory_file:
                default_memory = memory_file.read()
            self.assertIn("贷款系统开发流水线默认记忆", default_memory)
            self.assertIn("后端是业务事实和风控决策来源", default_memory)
            self.assertIn("加解密必须集中在网络层", default_memory)
            with open(memory_index_path, encoding="utf-8") as index_file:
                memory_index = index_file.read()
            self.assertIn("loan_pipeline_default.md", memory_index)
            self.assertIn("Network/", memory_index)

    def test_default_loan_memory_is_not_overwritten_when_present(self):
        with tempfile.TemporaryDirectory() as work_dir:
            memory_dir = os.path.join(work_dir, "memory")
            os.makedirs(memory_dir)
            default_memory_path = os.path.join(memory_dir, "loan_pipeline_default.md")
            with open(default_memory_path, "w", encoding="utf-8") as memory_file:
                memory_file.write("project-specific memory\n")

            environment._ensure_default_memory(work_dir)

            with open(default_memory_path, encoding="utf-8") as memory_file:
                self.assertEqual(memory_file.read(), "project-specific memory\n")

    def test_default_memory_tree_is_copied_without_overwriting_existing_files(self):
        with tempfile.TemporaryDirectory() as work_dir:
            target_network_dir = os.path.join(work_dir, "memory", "Network")
            os.makedirs(target_network_dir)
            target_network_file = os.path.join(target_network_dir, "NetworkClient.swift")
            with open(target_network_file, "w", encoding="utf-8") as network_file:
                network_file.write("project-specific network memory\n")

            environment._ensure_default_memory(work_dir)

            copied_crypto_file = os.path.join(work_dir, "memory", "Network", "RequestCrypto.swift")
            self.assertTrue(os.path.isfile(copied_crypto_file))
            with open(target_network_file, encoding="utf-8") as network_file:
                self.assertEqual(network_file.read(), "project-specific network memory\n")

    def test_future_default_memory_files_are_copied_and_indexed(self):
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

    def test_default_loan_memory_abstracts_network_demo_principles(self):
        template_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "default-memory",
            "loan_pipeline_default.md",
        )

        with open(template_path, encoding="utf-8") as template_file:
            template = template_file.read()

        self.assertIn("`Network/` demo", template)
        self.assertIn("逻辑 API", template)
        self.assertIn("请求加密失败时不上送", template)
        self.assertIn("明文响应必须旁路", template)
        self.assertIn("multipart", template)
        self.assertIn("download", template)
        self.assertIn("Debug Mock", template)


if __name__ == "__main__":
    unittest.main()

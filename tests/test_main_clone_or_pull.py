import os
import unittest
from unittest.mock import call, patch

import main


class CloneOrPullTests(unittest.TestCase):
    def test_clones_when_target_and_parent_repo_do_not_exist(self):
        repo_url = "http://example.test/group/ginkgo.git"
        branch = "feature/demo"
        target_path = os.path.join("/work", "stage", "ginkgo")

        with patch("main.os.path.exists", return_value=False), \
                patch("main.subprocess.run") as subprocess_run:
            main._clone_or_pull(repo_url, branch, target_path)

        subprocess_run.assert_called_once_with(
            ["git", "clone", repo_url, "-b", branch, target_path],
            check=True,
            capture_output=True,
            text=True,
        )

    def test_existing_non_git_target_fails_with_clear_error(self):
        repo_url = "http://example.test/group/ginkgo.git"
        branch = "feature/demo"
        target_path = os.path.join("/work", "stage", "ginkgo")

        with patch("main.os.path.exists", return_value=True), \
                patch("main.subprocess.run", return_value=unittest.mock.Mock(returncode=128, stdout="")):
            with self.assertRaisesRegex(RuntimeError, "目标路径已存在但不是 Git 仓库"):
                main._clone_or_pull(repo_url, branch, target_path)

    def test_updates_matching_parent_repo_when_target_path_is_nested_too_deep(self):
        repo_url = "http://example.test/group/ginkgo.git"
        branch = "feature/demo"
        target_path = os.path.join("/work", "ginkgo", "ginkgo")
        parent_path = os.path.dirname(target_path)

        def exists(path):
            return path == parent_path

        def run(args, **kwargs):
            if args == ["git", "-C", target_path, "rev-parse", "--is-inside-work-tree"]:
                raise main.subprocess.CalledProcessError(128, args)
            if args == ["git", "-C", parent_path, "rev-parse", "--is-inside-work-tree"]:
                return unittest.mock.Mock(returncode=0, stdout="true\n")
            if args == ["git", "-C", parent_path, "config", "--get", "remote.origin.url"]:
                return unittest.mock.Mock(returncode=0, stdout=repo_url + "\n")
            return unittest.mock.Mock(returncode=0, stdout="")

        with patch("main.os.path.exists", side_effect=exists), \
                patch("main.subprocess.run", side_effect=run) as subprocess_run:
            main._clone_or_pull(repo_url, branch, target_path)

        self.assertNotIn(
            call(["git", "clone", repo_url, "-b", branch, target_path], check=True, capture_output=True),
            subprocess_run.mock_calls,
        )
        self.assertIn(
            call(["git", "-C", parent_path, "checkout", branch], check=True, capture_output=True, text=True),
            subprocess_run.mock_calls,
        )
        self.assertIn(
            call(["git", "-C", parent_path, "pull"], check=True, capture_output=True, text=True),
            subprocess_run.mock_calls,
        )


if __name__ == "__main__":
    unittest.main()

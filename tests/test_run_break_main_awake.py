import os
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "run_break_main_awake.sh"


class AwakeWrapperTests(unittest.TestCase):
    def test_restarts_after_nonzero_exit_and_stops_after_zero_exit(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            state_file = temp_path / "state"
            fake_python = temp_path / "fake-python"
            fake_caffeinate = temp_path / "caffeinate"
            fake_python.write_text(
                "#!/bin/sh\n"
                f"state_file='{state_file}'\n"
                "count=0\n"
                "[ -f \"$state_file\" ] && count=$(cat \"$state_file\")\n"
                "count=$((count + 1))\n"
                "printf '%s' \"$count\" > \"$state_file\"\n"
                "[ \"$count\" -eq 1 ] && exit 7\n"
                "exit 0\n",
                encoding="utf-8",
            )
            fake_caffeinate.write_text(
                "#!/bin/sh\n"
                "shift\n"
                "exec \"$@\"\n",
                encoding="utf-8",
            )
            (temp_path / "sleep").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            fake_python.chmod(0o755)
            fake_caffeinate.chmod(0o755)
            (temp_path / "sleep").chmod(0o755)

            result = subprocess.run(
                ["bash", str(SCRIPT)],
                cwd=REPO_ROOT,
                env={
                    **os.environ,
                    "PATH": f"{temp_path}:{os.environ['PATH']}",
                    "PYTHON_BIN": str(fake_python),
                },
                capture_output=True,
                text=True,
                timeout=5,
            )
            run_count = state_file.read_text(encoding="utf-8")

        self.assertEqual(result.returncode, 0)
        self.assertEqual(run_count, "2")


if __name__ == "__main__":
    unittest.main()

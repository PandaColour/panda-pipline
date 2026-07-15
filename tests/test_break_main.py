import unittest
from unittest.mock import patch

import break_main


class BreakMainTests(unittest.TestCase):
    @patch("break_main.BreakPipeline")
    @patch("break_main.setup_environment", return_value="/tmp/target")
    def test_main_starts_break_pipeline(self, setup_environment, pipeline_class):
        break_main.main()

        pipeline_class.assert_called_once_with("/tmp/target")
        pipeline_class.return_value.run.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()

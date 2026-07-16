import unittest

import break_main
import environment
import main


class EnvironmentModuleTests(unittest.TestCase):
    def test_entry_points_use_the_independent_environment_module(self):
        self.assertIs(break_main.setup_environment, environment.setup_environment)
        self.assertIs(main.setup_environment, environment.setup_environment)


if __name__ == "__main__":
    unittest.main()

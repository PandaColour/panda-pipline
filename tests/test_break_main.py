import unittest
from unittest.mock import call, patch

import break_main
import main as normal_main


class BreakMainTests(unittest.TestCase):
    def test_execution_failure_exits_for_wrapper_restart(self):
        from task_protocol import TaskRetryRequired
        for module in (break_main, normal_main):
            with self.subTest(module=module.__name__), \
                    patch.object(module, '_main', side_effect=TaskRetryRequired('network_error; example.txt')), \
                    patch('builtins.print') as printed, self.assertRaises(SystemExit) as stopped:
                module.main()
            self.assertEqual(stopped.exception.code, 1)
            self.assertIn('脚本重新拉起', str(printed.call_args_list))

    def test_receipt_pending_exits_for_wrapper_restart_without_next_task(self):
        from task_protocol import ReceiptPending
        for module, pipeline_name in ((break_main, 'BreakPipeline'), (normal_main, 'Pipeline')):
            for resume in (True, False):
                with self.subTest(module=module.__name__, resume=resume), \
                        patch.object(module, 'setup_environment', return_value='/tmp/target'), \
                        patch.object(module.os.path, 'isfile', return_value=resume), \
                        patch.object(module, pipeline_name) as pipeline, \
                        patch('builtins.input', return_value='需求') as prompt, \
                        patch('builtins.print') as printed:
                    pipeline.return_value.run.side_effect = ReceiptPending('回执待补正：原始日志 example.txt')
                    with self.assertRaises(SystemExit) as stopped:
                        module.main()
                    self.assertEqual(stopped.exception.code, 1)
                    pipeline.return_value.run.assert_called_once()
                    self.assertEqual(prompt.call_count, 0 if resume else 1)
                    self.assertIn('example.txt', str(printed.call_args_list))

    @patch("break_main.BreakPipeline")
    @patch("break_main.setup_environment", return_value="/tmp/target")
    def test_main_starts_break_pipeline(self, setup_environment, pipeline_class):
        with patch("builtins.input", side_effect=["做拆分需求", "exit"]):
            break_main.main()

        pipeline_class.assert_called_once_with("/tmp/target")
        pipeline_class.return_value.run.assert_called_once_with("做拆分需求")

    @patch("break_main.BreakPipeline")
    @patch("break_main.setup_environment", return_value="/tmp/target")
    def test_skip_human_flag_is_passed_to_break_pipeline(self, setup_environment, pipeline_class):
        with patch("builtins.input", side_effect=["做拆分需求", "exit"]):
            break_main.main(["--skipHuman"])

        pipeline_class.assert_called_once_with("/tmp/target", skip_human=True)

    @patch("main.Pipeline")
    @patch("main.setup_environment", return_value="/tmp/target")
    def test_skip_human_flag_is_passed_to_normal_pipeline(self, setup_environment, pipeline_class):
        with patch("builtins.input", side_effect=["做普通需求", "exit"]):
            normal_main.main(["--skipHuman"])

        pipeline_class.assert_called_once_with("/tmp/target", skip_human=True)

    @patch("main.Pipeline")
    @patch("main.setup_environment", return_value="/tmp/target")
    def test_normal_main_keeps_accepting_requirements_until_exit(self, setup_environment, pipeline_class):
        with patch("builtins.input", side_effect=["第一个需求", "补充说明", "quit"]):
            normal_main.main()

        self.assertEqual(
            pipeline_class.call_args_list,
            [call("/tmp/target"), call("/tmp/target")],
        )
        self.assertEqual(
            pipeline_class.return_value.run.call_args_list,
            [call("第一个需求"), call("补充说明")],
        )

    @patch("break_main.BreakPipeline")
    @patch("break_main.setup_environment", return_value="/tmp/target")
    def test_break_main_keeps_accepting_requirements_until_exit(self, setup_environment, pipeline_class):
        with patch("builtins.input", side_effect=["第一个大需求", "补充拆分说明", "q"]):
            break_main.main()

        self.assertEqual(
            pipeline_class.call_args_list,
            [call("/tmp/target"), call("/tmp/target")],
        )
        self.assertEqual(
            pipeline_class.return_value.run.call_args_list,
            [call("第一个大需求"), call("补充拆分说明")],
        )

    @patch("break_main.BreakPipeline")
    @patch("break_main.setup_environment", return_value="/tmp/target")
    @patch("break_main.os.path.isfile", return_value=True)
    def test_break_main_resumes_before_prompting_when_state_exists(self, isfile, setup_environment, pipeline_class):
        pipeline_class.return_value.has_resumable_state.return_value = True

        with patch("builtins.input", side_effect=["新的大需求", "q"]):
            break_main.main()

        self.assertEqual(
            pipeline_class.return_value.run.call_args_list,
            [call(None), call("新的大需求")],
        )


class NormalMainRestartTests(unittest.TestCase):
    @patch("main.Pipeline")
    @patch("main.setup_environment", return_value="/tmp/target")
    @patch("main.os.path.isfile", return_value=True)
    def test_main_resumes_before_prompting_when_state_exists(self, isfile, setup_environment, pipeline_class):
        pipeline_class.return_value.has_resumable_state.return_value = True

        with patch("builtins.input", side_effect=["新的需求", "q"]):
            normal_main.main()

        self.assertEqual(
            pipeline_class.return_value.run.call_args_list,
            [call(None), call("新的需求")],
        )


if __name__ == "__main__":
    unittest.main()

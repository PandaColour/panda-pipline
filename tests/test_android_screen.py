import unittest

from tests.skill_scripts import android_screen

screen_report = android_screen.screen_report
screen_target = android_screen.screen_target


class ScreenTests(unittest.TestCase):
    def test_default_font_and_effective_override_dimensions(self):
        report = screen_report('Physical size: 1080x2400\nOverride size: 750x1624',
                               'Physical density: 420\nOverride density: 320', 'null',
                               screen_target(750, 1624, 320))
        self.assertTrue(report['matches_target'])
        self.assertEqual(report['logical_width_dp'], 375)
        self.assertEqual(report['logical_height_dp'], 812)
        self.assertEqual(report['font_scale'], 1)

    def test_unreadable_measurements_never_claim_match(self):
        report = screen_report('', 'permission denied', '', screen_target(750, 1624, 320))
        self.assertIsNone(report['matches_target'])
        self.assertIsNone(report['logical_width_dp'])
        self.assertTrue(report['warnings'])

    def test_nondefault_font_is_reported_separately(self):
        report = screen_report('Physical size: 750x1624', 'Physical density: 320', '1.3',
                               screen_target(750, 1624, 320))
        self.assertTrue(report['matches_target'])
        self.assertEqual(report['font_scale'], 1.3)
        self.assertTrue(report['warnings'])

    def test_invalid_baselines_rejected(self):
        for values in [(750, None, 320), (0, 1624, 320), (750, 1624, -1)]:
            with self.assertRaises(ValueError):
                screen_target(*values)

    def test_dp_passed_as_pixels_exposes_requested_logical_size(self):
        target = screen_target(375, 812, 320)
        report = screen_report('Physical size: 750x1624', 'Physical density: 320', '1', target)
        self.assertEqual(report.get('target_logical_width_dp'), 187.5)
        self.assertEqual(report.get('target_logical_height_dp'), 406)
        self.assertEqual(report['logical_width_dp'], 375)
        self.assertEqual(report['logical_height_dp'], 812)
        self.assertFalse(report['matches_target'])
        self.assertEqual(target, {'width_px': 375, 'height_px': 812, 'density_dpi': 320})
        warning = '\n'.join(report['warnings'])
        for value in ('187.5', '406', '375', '812', 'px', 'dp'):
            self.assertIn(value, warning)

    def test_correct_pixel_target_reports_same_logical_size_without_warning(self):
        report = screen_report('Physical size: 750x1624', 'Physical density: 320', '1',
                               screen_target(750, 1624, 320))
        self.assertEqual(report.get('target_logical_width_dp'), 375)
        self.assertEqual(report.get('target_logical_height_dp'), 812)
        self.assertTrue(report['matches_target'])
        self.assertEqual(report['warnings'], [])

    def test_unknown_actual_size_keeps_requested_logical_size(self):
        report = screen_report('', '', '', screen_target(750, 1624, 320))
        self.assertEqual(report.get('target_logical_width_dp'), 375)
        self.assertEqual(report.get('target_logical_height_dp'), 812)
        self.assertIsNone(report['matches_target'])
        self.assertIsNone(report['logical_width_dp'])

    def test_no_target_does_not_infer_one_from_device(self):
        report = screen_report('Physical size: 750x1624', 'Physical density: 320', '1')
        self.assertIn('target_logical_width_dp', report)
        self.assertIsNone(report['target_logical_width_dp'])
        self.assertIsNone(report['target_logical_height_dp'])
        self.assertIsNone(report['target'])
        self.assertIsNone(report['matches_target'])

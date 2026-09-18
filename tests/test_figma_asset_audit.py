import json
import hashlib
import struct
import tempfile
import unittest
import zlib
from pathlib import Path

from tests.skill_scripts import figma_asset_audit

audit_requirements = figma_asset_audit.audit_requirements
main = figma_asset_audit.main


class FigmaAssetAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.requirements_dir = self.root / "requirements"
        self.requirements_dir.mkdir()

    def tearDown(self):
        self.temp_dir.cleanup()

    def _png(self, path, width=2, height=2):
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = b"".join(b"\x00" + b"\x00\x00\x00\xff" * width for _ in range(height))

        def chunk(kind, data):
            return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

        path.write_bytes(
            b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw))
            + chunk(b"IEND", b"")
        )

    def _fixture(self, requirement_id="R-003", frame_name="H-05-loading", node_id="143:4432"):
        inventory_path = self.requirements_dir / "_figma_inventory.json"
        inventory = json.loads(inventory_path.read_text()) if inventory_path.exists() else {}
        inventory[requirement_id] = [[frame_name, node_id.replace(":", "-"), "加载态"]]
        inventory_path.write_text(json.dumps(inventory), encoding="utf-8")

        requirement_dir = self.requirements_dir / f"{requirement_id}-example"
        assets_dir = requirement_dir / "figma_assets"
        reference = assets_dir / "reference_screens" / "h05_loading.png"
        icon = assets_dir / "icons" / "loading_spinner.svg"
        self._png(reference, 4, 4)
        icon.parent.mkdir(parents=True, exist_ok=True)
        icon.write_text('<svg xmlns="http://www.w3.org/2000/svg"/>', encoding="utf-8")
        manifest = {
            "schema_version": 1,
            "requirement_id": requirement_id,
            "figma_file_key": "file-key",
            "frames": [{
                "name": frame_name,
                "node_id": node_id,
                "state": "加载态",
                "remote_read": {"status": "success", "tool": "get_figma_node"},
                "reference_screen": {
                    "path": "figma_assets/reference_screens/h05_loading.png",
                    "format": "PNG @2x",
                },
                "assets": [{
                    "node_id": "143:4433",
                    "name": "loading_spinner",
                    "kind": "vector",
                    "discovery": "export-tagged",
                    "decision": "export",
                    "format": "SVG",
                    "local_path": "figma_assets/icons/loading_spinner.svg",
                    "usage": "H-05 loading spinner",
                }],
            }],
        }
        (assets_dir / "asset_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        requirement_dir.joinpath("user_requirements.md").write_text(
            "# Requirement\n\n### 物料映射表\n\n"
            "| Figma 来源节点 ID | 本地相对路径 | 类型 |\n|---|---|---|\n"
            "| 143:4432 | `figma_assets/reference_screens/h05_loading.png` | 参考图 |\n"
            "| 143:4433 | `figma_assets/icons/loading_spinner.svg` | icon |\n\n## Next\n",
            encoding="utf-8",
        )
        return requirement_dir, manifest

    def _codes(self, report):
        return {issue["code"] for issue in report["issues"]}

    def _selected_fixture(self):
        directory, manifest = self._fixture()
        manifest["schema_version"] = 2
        manifest["frames"][0]["assets"][0].update(
            required=True, selection_evidence="AC-01 loading state uses node 143:4433"
        )
        return directory, manifest

    def _save_and_audit(self, directory, manifest):
        (directory / "figma_assets/asset_manifest.json").write_text(json.dumps(manifest))
        return audit_requirements(self.requirements_dir)

    def _indexed_fixture(self):
        directory, manifest = self._selected_fixture()
        manifest['schema_version'] = 3
        source = directory / 'figma_assets/design_sources/loading.json'
        source.parent.mkdir(exist_ok=True)
        source.write_text(json.dumps({'id': '143:4432', 'name': 'Loading', 'children': []}))
        manifest['frames'][0]['design_source'] = {
            'path': 'figma_assets/design_sources/loading.json',
            'sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
            'node_id': '143:4432', 'revision': 'version-1',
        }
        return directory, manifest

    def test_index_survives_document_simplification_and_new_analyst_assets(self):
        directory, manifest = self._indexed_fixture()
        original = directory / 'user_requirements.md'
        original.write_text('# Requirement\nSee figma_assets/asset_manifest.json\n')
        (directory / 'requirements_analysis.md').write_text('## UI\nSee figma_assets/asset_manifest.json\n')
        extra = directory / 'figma_assets/icons/close.svg'
        extra.write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
        manifest['frames'][0]['assets'].append(dict(
            manifest['frames'][0]['assets'][0], node_id='143:9000',
            local_path='figma_assets/icons/close.svg', usage='close button',
            selection_evidence='AC-02 close button'))
        report = self._save_and_audit(directory, manifest)
        self.assertEqual('passed', report['status'])
        self.assertEqual(2, report['totals']['exported_assets'])
        self.assertEqual(original.read_text(), '# Requirement\nSee figma_assets/asset_manifest.json\n')

    def test_index_does_not_need_markdown_mapping_document(self):
        directory, manifest = self._indexed_fixture()
        (directory / 'user_requirements.md').unlink()
        self.assertEqual('passed', self._save_and_audit(directory, manifest)['status'])

    def test_index_requires_design_source_for_each_frame(self):
        directory, manifest = self._indexed_fixture()
        del manifest['frames'][0]['design_source']
        self.assertIn('design_source_missing', self._codes(self._save_and_audit(directory, manifest)))

    def test_index_rejects_missing_corrupt_or_changed_source(self):
        for kind in ('missing', 'corrupt', 'changed', 'empty'):
            with self.subTest(kind=kind):
                directory, manifest = self._indexed_fixture()
                record = manifest['frames'][0]['design_source']
                source = directory / record['path']
                if kind == 'missing':
                    source.unlink()
                else:
                    source.write_text({'corrupt': '{', 'changed': '{"id":"143:4432","name":"changed"}', 'empty': '{}'}[kind])
                    if kind != 'changed':
                        record['sha256'] = hashlib.sha256(source.read_bytes()).hexdigest()
                report = self._save_and_audit(directory, manifest)
                self.assertIn('design_source_invalid', self._codes(report))

    def test_index_rejects_source_path_escape_and_wrong_identity(self):
        for field, value in [('path', '../outside.json'), ('node_id', '143:9999'), ('revision', '')]:
            with self.subTest(field=field):
                directory, manifest = self._indexed_fixture()
                manifest['frames'][0]['design_source'][field] = value
                self.assertIn('design_source_invalid', self._codes(self._save_and_audit(directory, manifest)))

    def test_local_source_survives_current_mcp_failure_without_faking_remote_success(self):
        directory, manifest = self._indexed_fixture()
        manifest['frames'][0]['remote_read'] = {'status': 'failed', 'tool': 'get_figma_node', 'reason': '429'}
        report = self._save_and_audit(directory, manifest)
        self.assertEqual('passed', report['status'])
        self.assertEqual(0, report['totals']['remote_reads'])
        manifest['frames'][0]['remote_read'].pop('reason')
        self.assertIn('remote_read_incomplete', self._codes(self._save_and_audit(directory, manifest)))

    def test_index_still_rejects_missing_and_untracked_business_assets(self):
        directory, manifest = self._indexed_fixture()
        (directory / manifest['frames'][0]['assets'][0]['local_path']).unlink()
        (directory / 'figma_assets/icons/unknown.svg').write_text('<svg/>')
        codes = self._codes(self._save_and_audit(directory, manifest))
        self.assertIn('asset_file_missing', codes)
        self.assertIn('untracked_asset_file', codes)

    def test_index_rejects_absolute_material_paths_even_inside_requirement(self):
        directory, manifest = self._indexed_fixture()
        for record, key in [(manifest['frames'][0]['reference_screen'], 'path'),
                            (manifest['frames'][0]['assets'][0], 'local_path')]:
            record[key] = str(directory / record[key])
        report = self._save_and_audit(directory, manifest)
        self.assertEqual(2, sum(i['code'] == 'asset_path_invalid' for i in report['issues']))

    def test_rest_source_is_not_counted_as_successful_mcp_read(self):
        directory, manifest = self._indexed_fixture()
        manifest['frames'][0]['remote_read'] = {'status': 'success', 'tool': 'REST'}
        report = self._save_and_audit(directory, manifest)
        self.assertEqual('passed', report['status'])
        self.assertEqual(0, report['totals']['remote_reads'])

    def test_index_relative_paths_survive_requirements_archive(self):
        directory, manifest = self._indexed_fixture()
        self._save_and_audit(directory, manifest)
        archive = self.root / 'requirements-archive'
        self.requirements_dir.rename(archive)
        self.assertEqual('passed', audit_requirements(archive)['status'])

    def test_legacy_audit_explicitly_discloses_unchecked_design_sources(self):
        self._fixture()
        report = audit_requirements(self.requirements_dir)
        self.assertEqual('passed', report['status'])
        self.assertEqual(['R-003'], report['legacy_requirements'])

    def test_unused_image_candidate_does_not_require_download(self):
        directory, manifest = self._selected_fixture()
        manifest["frames"][0]["assets"].append({
            "node_id": "143:9999", "discovery": "imageAssets", "usage": "unused variant",
            "required": False, "selection_evidence": "AC-01 uses loading, not archived variant 143:9999",
            "decision": "skip", "skip_reason": "not used in any target state",
        })
        self.assertEqual("passed", self._save_and_audit(directory, manifest)["status"])

    def test_selection_requires_evidence_and_required_asset_cannot_skip(self):
        directory, manifest = self._selected_fixture()
        asset = manifest["frames"][0]["assets"][0]
        asset.update(decision="skip", skip_reason="not export tagged", selection_evidence="")
        codes = self._codes(self._save_and_audit(directory, manifest))
        self.assertIn("asset_selection_invalid", codes)
        self.assertIn("forbidden_asset_skip", codes)

    def test_reuse_checks_file_and_mapping_without_duplicate_export(self):
        directory, manifest = self._selected_fixture()
        asset = manifest["frames"][0]["assets"][0]
        reused = dict(asset, node_id="143:4434", decision="reuse")
        manifest["frames"][0]["assets"].append(reused)
        mapping = directory / "user_requirements.md"
        mapping.write_text(mapping.read_text().replace(
            "## Next", "| 143:4434 | `figma_assets/icons/loading_spinner.svg` | icon |\n\n## Next"
        ))
        self.assertEqual("passed", self._save_and_audit(directory, manifest)["status"])
        (directory / asset["local_path"]).unlink()
        self.assertIn("asset_file_missing", self._codes(self._save_and_audit(directory, manifest)))

    def test_unnecessary_download_and_unresolved_decisions_fail(self):
        directory, manifest = self._selected_fixture()
        asset = manifest["frames"][0]["assets"][0]
        asset["required"] = False
        self.assertIn("unnecessary_asset_export", self._codes(self._save_and_audit(directory, manifest)))
        asset.update(required=True, decision="pending")
        self.assertIn("asset_decision_missing", self._codes(self._save_and_audit(directory, manifest)))

    def test_animation_cannot_be_delivered_as_static_preview(self):
        directory, manifest = self._selected_fixture()
        manifest["frames"][0]["assets"][0].update(kind="animation", format="PNG")
        self.assertIn("motion_evidence_missing", self._codes(self._save_and_audit(directory, manifest)))

    def test_complete_manifest_mapping_and_files_pass(self):
        self._fixture()
        report = audit_requirements(self.requirements_dir)
        self.assertEqual("passed", report["status"])
        self.assertEqual([], report["issues"])
        self.assertEqual(1, report["totals"]["frames"])
        self.assertEqual(1, report["totals"]["exported_assets"])

    def test_reference_only_frames_fail_even_when_declared_paths_exist(self):
        requirement_dir, _ = self._fixture()
        mapping = requirement_dir / "user_requirements.md"
        mapping.write_text(
            mapping.read_text(encoding="utf-8").replace(
                "| 143:4433 | `figma_assets/icons/loading_spinner.svg` | icon |\n", ""
            ),
            encoding="utf-8",
        )
        report = audit_requirements(self.requirements_dir)
        self.assertIn("asset_mapping_missing", self._codes(report))
        self.assertIn("reference_only_frame", self._codes(report))

    def test_inventory_frame_missing_from_manifest_fails(self):
        requirement_dir, manifest = self._fixture()
        manifest["frames"] = []
        (requirement_dir / "figma_assets/asset_manifest.json").write_text(json.dumps(manifest))
        self.assertIn("inventory_frame_missing", self._codes(audit_requirements(self.requirements_dir)))

    def test_inventory_frame_identity_mismatch_fails(self):
        requirement_dir, manifest = self._fixture()
        manifest["frames"][0]["state"] = "正常态"
        (requirement_dir / "figma_assets/asset_manifest.json").write_text(json.dumps(manifest))
        report = audit_requirements(self.requirements_dir)
        self.assertIn("inventory_frame_missing", self._codes(report))
        self.assertIn("inventory_frame_mismatch", self._codes(report))

    def test_remote_read_must_be_successful_get_figma_node(self):
        requirement_dir, manifest = self._fixture()
        manifest["frames"][0]["remote_read"] = {"status": "blocked", "reason": "network down"}
        (requirement_dir / "figma_assets/asset_manifest.json").write_text(json.dumps(manifest))
        self.assertIn("remote_read_incomplete", self._codes(audit_requirements(self.requirements_dir)))

    def test_missing_reference_screen_fails(self):
        requirement_dir, manifest = self._fixture()
        manifest["frames"][0].pop("reference_screen")
        (requirement_dir / "figma_assets/asset_manifest.json").write_text(json.dumps(manifest))
        self.assertIn("reference_screen_missing", self._codes(audit_requirements(self.requirements_dir)))

    def test_export_tagged_asset_cannot_be_skipped(self):
        requirement_dir, manifest = self._fixture()
        asset = manifest["frames"][0]["assets"][0]
        asset.update({"decision": "skip", "skip_reason": "Compose 可绘制"})
        asset.pop("local_path")
        asset.pop("format")
        (requirement_dir / "figma_assets/asset_manifest.json").write_text(json.dumps(manifest))
        self.assertIn("forbidden_asset_skip", self._codes(audit_requirements(self.requirements_dir)))

    def test_untracked_business_asset_fails(self):
        requirement_dir, _ = self._fixture()
        (requirement_dir / "figma_assets/icons/extra.svg").write_text("<svg/>")
        self.assertIn("untracked_asset_file", self._codes(audit_requirements(self.requirements_dir)))

    def test_exported_asset_missing_from_disk_fails(self):
        requirement_dir, _ = self._fixture()
        (requirement_dir / "figma_assets/icons/loading_spinner.svg").unlink()
        self.assertIn("asset_file_missing", self._codes(audit_requirements(self.requirements_dir)))

    def test_untracked_mapping_entry_fails(self):
        requirement_dir, _ = self._fixture()
        mapping = requirement_dir / "user_requirements.md"
        mapping.write_text(
            mapping.read_text(encoding="utf-8").replace(
                "\n## Next\n",
                "| 260:4117 | `figma_assets/icons/toast_success.svg` | icon |\n\n## Next\n",
            ),
            encoding="utf-8",
        )
        self.assertIn("untracked_mapping_entry", self._codes(audit_requirements(self.requirements_dir)))

    def test_malformed_svg_and_png_fail(self):
        requirement_dir, _ = self._fixture()
        (requirement_dir / "figma_assets/icons/loading_spinner.svg").write_text("not svg")
        report = audit_requirements(self.requirements_dir)
        self.assertIn("invalid_svg", self._codes(report))

        (requirement_dir / "figma_assets/icons/loading_spinner.svg").write_text("<svg/>")
        (requirement_dir / "figma_assets/reference_screens/h05_loading.png").write_bytes(b"not png")
        report = audit_requirements(self.requirements_dir)
        self.assertIn("invalid_png", self._codes(report))

    def test_invalid_png_scale_fails_when_design_size_is_declared(self):
        requirement_dir, manifest = self._fixture()
        reference = manifest["frames"][0]["reference_screen"]
        reference.update({"design_width": 3, "design_height": 3, "scale": 2})
        (requirement_dir / "figma_assets/asset_manifest.json").write_text(json.dumps(manifest))
        self.assertIn("invalid_png_scale", self._codes(audit_requirements(self.requirements_dir)))

    def test_requirement_scope_ignores_other_broken_requirement(self):
        self._fixture("R-003")
        other_dir, other = self._fixture("R-004", "A-03-login", "99:981")
        other["frames"] = []
        (other_dir / "figma_assets/asset_manifest.json").write_text(json.dumps(other))
        report = audit_requirements(self.requirements_dir, "R-003")
        self.assertEqual("passed", report["status"])

    def test_cli_writes_report_and_uses_exit_codes(self):
        self._fixture()
        report_path = self.root / "audit.json"
        self.assertEqual(0, main([
            "--requirements-dir", str(self.requirements_dir), "--report", str(report_path)
        ]))
        self.assertEqual("passed", json.loads(report_path.read_text())["status"])
        (self.requirements_dir / "_figma_inventory.json").write_text("[]")
        self.assertEqual(2, main([
            "--requirements-dir", str(self.requirements_dir), "--report", str(report_path)
        ]))
        self.assertEqual("error", json.loads(report_path.read_text())["status"])


if __name__ == "__main__":
    unittest.main()

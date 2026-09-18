"""Read-only completeness audit for Agent-prepared Figma material packages."""

import argparse
import hashlib
import json
import re
import struct
import xml.etree.ElementTree as ET
from pathlib import Path


NODE_ID_PATTERN = re.compile(r"^[^:\s]+:[^:\s]+$")
MAPPING_PATH_PATTERN = re.compile(r"`([^`]+)`")
ALLOWED_DISCOVERY = {"imageAssets", "imageRef", "export-tagged", "nested-custom-asset", "font"}
NON_SKIPPABLE_DISCOVERY = {"imageAssets", "imageRef", "export-tagged", "nested-custom-asset"}
BUSINESS_EXTENSIONS = {".png", ".svg", ".jpg", ".jpeg", ".webp", ".ttf", ".otf", ".gif", ".mp4", ".webm", ".json"}


class AuditInputError(ValueError):
    """Raised when audit inputs cannot be parsed or violate the manifest schema."""


def normalize_node_id(value):
    text = str(value).strip()
    if ":" not in text and "-" in text:
        text = text.replace("-", ":", 1)
    if not NODE_ID_PATTERN.fullmatch(text):
        raise AuditInputError(f"invalid Figma node-id: {value!r}")
    return text


def _load_json(path):
    try:
        with Path(path).open(encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError) as error:
        raise AuditInputError(f"cannot read JSON {path}: {error}") from error


def _load_inventory(requirements_dir):
    inventory = _load_json(Path(requirements_dir) / "_figma_inventory.json")
    if not isinstance(inventory, dict):
        raise AuditInputError("_figma_inventory.json must be an object")
    normalized = {}
    for requirement_id, frames in inventory.items():
        if not isinstance(requirement_id, str) or not isinstance(frames, list):
            raise AuditInputError("inventory entries must map requirement ids to frame lists")
        normalized_frames = []
        for frame in frames:
            if not isinstance(frame, list) or len(frame) != 3:
                raise AuditInputError(f"invalid inventory frame for {requirement_id}: {frame!r}")
            normalized_frames.append({
                "name": str(frame[0]).strip(),
                "node_id": normalize_node_id(frame[1]),
                "state": str(frame[2]).strip(),
            })
        normalized[requirement_id] = normalized_frames
    return normalized


def _find_requirement_dir(requirements_dir, requirement_id):
    matches = sorted(path for path in Path(requirements_dir).glob(f"{requirement_id}-*") if path.is_dir())
    if len(matches) != 1:
        raise AuditInputError(f"expected one directory for {requirement_id}, found {len(matches)}")
    return matches[0]


def _issue(code, requirement_id, message, frame_node_id="", asset_node_id="", path=""):
    return {
        "code": code,
        "requirement_id": requirement_id,
        "frame_node_id": frame_node_id,
        "asset_node_id": asset_node_id,
        "path": path,
        "message": message,
    }


def _mapping_entries(requirement_dir):
    path = requirement_dir / "user_requirements.md"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise AuditInputError(f"cannot read mapping document {path}: {error}") from error
    in_section = False
    entries = set()
    for line in lines:
        if line.strip().startswith("### 物料映射表"):
            in_section = True
            continue
        if in_section and line.startswith("#"):
            break
        if not in_section or "|" not in line:
            continue
        columns = [column.strip() for column in line.strip().strip("|").split("|")]
        if len(columns) < 2:
            continue
        path_match = MAPPING_PATH_PATTERN.search(columns[1])
        if not path_match:
            continue
        try:
            node_id = normalize_node_id(columns[0])
        except AuditInputError:
            continue
        entries.add((node_id, path_match.group(1)))
    return entries


def _safe_local_path(requirement_dir, relative_path):
    candidate = (requirement_dir / relative_path).resolve()
    root = requirement_dir.resolve()
    if candidate != root and root not in candidate.parents:
        raise AuditInputError(f"asset path escapes requirement directory: {relative_path}")
    return candidate


def _png_size(path):
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        return None
    return struct.unpack(">II", data[16:24])


def _valid_svg(path):
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError):
        return False
    return root.tag.rsplit("}", 1)[-1].lower() == "svg"


def _validate_file(requirement_id, frame_id, asset_id, relative_path, format_name, record, requirement_dir, *, relative_only=False):
    issues = []
    try:
        if relative_only and Path(relative_path).is_absolute():
            raise AuditInputError('asset path must be relative to the requirement directory')
        path = _safe_local_path(requirement_dir, relative_path)
    except AuditInputError as error:
        return [_issue("asset_path_invalid", requirement_id, str(error), frame_id, asset_id, relative_path)]
    if not path.is_file() or path.stat().st_size == 0:
        return [_issue("asset_file_missing", requirement_id, "exported asset file is missing or empty", frame_id, asset_id, relative_path)]
    upper_format = str(format_name).upper()
    if upper_format.startswith("SVG"):
        if path.suffix.lower() != ".svg" or not _valid_svg(path):
            issues.append(_issue("invalid_svg", requirement_id, "SVG is missing, malformed, or has the wrong extension", frame_id, asset_id, relative_path))
    elif upper_format.startswith("PNG"):
        size = _png_size(path)
        if path.suffix.lower() != ".png" or size is None:
            issues.append(_issue("invalid_png", requirement_id, "PNG is missing, malformed, or has the wrong extension", frame_id, asset_id, relative_path))
        elif all(key in record for key in ("design_width", "design_height", "scale")):
            expected = (
                int(record["design_width"]) * int(record["scale"]),
                int(record["design_height"]) * int(record["scale"]),
            )
            if size != expected:
                issues.append(_issue("invalid_png_scale", requirement_id, f"PNG size {size} does not match expected {expected}", frame_id, asset_id, relative_path))
    return issues


def _validate_design_source(requirement_dir, requirement_id, frame_id, record):
    if not isinstance(record, dict) or not record.get('path'):
        return None, [_issue('design_source_missing', requirement_id,
                             'FRAME lacks a local design_source record', frame_id)]
    relative_path = record['path']
    try:
        if not isinstance(relative_path, str) or Path(relative_path).is_absolute():
            raise ValueError('design source path must be relative to the requirement directory')
        if normalize_node_id(record.get('node_id', '')) != frame_id:
            raise ValueError('design source node_id does not match FRAME')
        if not isinstance(record.get('revision'), str) or not record['revision'].strip():
            raise ValueError('design source revision is missing')
        path = _safe_local_path(requirement_dir, relative_path)
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != record.get('sha256'):
            raise ValueError('design source sha256 does not match local file')
        data = json.loads(content)
        if not isinstance(data, (dict, list)) or not data:
            raise ValueError('design source must contain a nonempty original JSON response')
    except (AuditInputError, OSError, ValueError, TypeError) as error:
        return relative_path if isinstance(relative_path, str) else None, [
            _issue('design_source_invalid', requirement_id, str(error), frame_id,
                   path=str(relative_path))]
    return relative_path, []


def _audit_requirement(requirements_dir, requirement_id, inventory_frames):
    requirement_dir = _find_requirement_dir(requirements_dir, requirement_id)
    manifest_path = requirement_dir / "figma_assets" / "asset_manifest.json"
    manifest = _load_json(manifest_path)
    if not isinstance(manifest, dict) or manifest.get("schema_version") not in (1, 2, 3):
        raise AuditInputError(f"unsupported asset manifest schema: {manifest_path}")
    if manifest.get("requirement_id") != requirement_id or not isinstance(manifest.get("frames"), list):
        raise AuditInputError(f"invalid asset manifest identity or frames: {manifest_path}")
    indexed = manifest['schema_version'] == 3
    # In v3, FRAME + reference_screen + assets is the authoritative mapping.
    # Keep the old document parser only for unmodified legacy packages.
    mapping = set() if indexed else _mapping_entries(requirement_dir)
    scoped_selection = manifest["schema_version"] >= 2
    issues = []
    tracked_paths = {"figma_assets/asset_manifest.json"}
    counts = {"frames": len(inventory_frames), "remote_reads": 0, "discovered_assets": 0, "required_assets": 0, "exported_assets": 0, "reused_assets": 0, "skipped_assets": 0, "missing": 0,
              "design_sources": 0, "legacy_manifests": int(not indexed)}

    expected = {(frame["name"], frame["node_id"], frame["state"]): frame for frame in inventory_frames}
    actual = {}
    for frame in manifest["frames"]:
        if not isinstance(frame, dict):
            raise AuditInputError(f"manifest frame must be an object: {manifest_path}")
        key = (str(frame.get("name", "")).strip(), normalize_node_id(frame.get("node_id", "")), str(frame.get("state", "")).strip())
        actual[key] = frame
    for key in sorted(expected.keys() - actual.keys()):
        issues.append(_issue("inventory_frame_missing", requirement_id, f"inventory frame missing from manifest: {key[0]}", key[1]))
    for key in sorted(actual.keys() - expected.keys()):
        issues.append(_issue("inventory_frame_mismatch", requirement_id, f"manifest frame is absent or differs from inventory: {key[0]}", key[1]))

    for key, frame in actual.items():
        frame_id = key[1]
        if indexed:
            source_path, source_issues = _validate_design_source(
                requirement_dir, requirement_id, frame_id, frame.get('design_source'))
            if source_path:
                tracked_paths.add(source_path)
            issues.extend(source_issues)
            if not source_issues:
                counts['design_sources'] += 1
        remote = frame.get("remote_read")
        if isinstance(remote, dict) and remote.get("status") == "success" and remote.get("tool") == "get_figma_node":
            counts["remote_reads"] += 1
        elif indexed and isinstance(remote, dict) and (
            (remote.get('status') == 'failed' and isinstance(remote.get('reason'), str) and remote['reason'].strip())
            or (remote.get('status') == 'success' and isinstance(remote.get('tool'), str) and remote['tool'].strip())
        ):
            # Local material completeness is independent of current MCP access.
            # REST success is not counted as a get_figma_node success.
            pass
        else:
            message = ('FRAME lacks an actual tool result or a failure reason' if indexed
                       else 'FRAME lacks successful get_figma_node evidence')
            issues.append(_issue("remote_read_incomplete", requirement_id, message, frame_id))
        reference = frame.get("reference_screen")
        if not isinstance(reference, dict) or not reference.get("path"):
            issues.append(_issue("reference_screen_missing", requirement_id, "FRAME lacks a reference screen record", frame_id))
        else:
            ref_path = str(reference["path"])
            tracked_paths.add(ref_path)
            issues.extend(_validate_file(requirement_id, frame_id, frame_id, ref_path, reference.get("format", ""), reference, requirement_dir, relative_only=indexed))
            if not indexed and (frame_id, ref_path) not in mapping:
                issues.append(_issue("reference_mapping_missing", requirement_id, "reference screen is absent from material mapping", frame_id, frame_id, ref_path))

        assets = frame.get("assets")
        if not isinstance(assets, list):
            raise AuditInputError(f"assets must be a list for frame {frame_id}")
        counts["discovered_assets"] += len(assets)
        successful_exports = 0
        exportable_seen = False
        for asset in assets:
            if not isinstance(asset, dict):
                raise AuditInputError(f"asset must be an object for frame {frame_id}")
            asset_id = normalize_node_id(asset.get("node_id", ""))
            discovery = asset.get("discovery")
            decision = asset.get("decision")
            if discovery not in ALLOWED_DISCOVERY or not str(asset.get("usage", "")).strip():
                issues.append(_issue("asset_record_invalid", requirement_id, "asset has invalid discovery or missing usage", frame_id, asset_id))
            required = asset.get("required") if scoped_selection else discovery in NON_SKIPPABLE_DISCOVERY
            if scoped_selection and (
                type(required) is not bool
                or not isinstance(asset.get("selection_evidence"), str)
                or not asset["selection_evidence"].strip()
            ):
                issues.append(_issue("asset_selection_invalid", requirement_id, "asset requires a boolean required and selection evidence", frame_id, asset_id))
            if required is True:
                counts["required_assets"] += 1
                exportable_seen = True
            if decision == "skip":
                counts["skipped_assets"] += 1
                reason = str(asset.get("skip_reason", "")).strip()
                if required is not False or not reason:
                    issues.append(_issue("forbidden_asset_skip", requirement_id, "independent business asset cannot be skipped", frame_id, asset_id))
                continue
            if decision not in (("export", "reuse") if scoped_selection else ("export",)):
                issues.append(_issue("asset_decision_missing", requirement_id, "asset decision must be export, reuse (schema 2/3), or skip", frame_id, asset_id))
                continue
            if scoped_selection and required is not True:
                issues.append(_issue("unnecessary_asset_export", requirement_id, "only required assets may be exported or reused", frame_id, asset_id))
            if scoped_selection and asset.get("kind") in ("animation", "video"):
                if str(asset.get("format", "")).upper() not in {"GIF", "WEBP", "MP4", "WEBM", "LOTTIE", "JSON"} or not asset.get("animation_evidence"):
                    issues.append(_issue("motion_evidence_missing", requirement_id, "motion requires original media and playback evidence; a static preview is insufficient", frame_id, asset_id))
            counts["reused_assets" if decision == "reuse" else "exported_assets"] += 1
            relative_path = str(asset.get("local_path", "")).strip()
            format_name = str(asset.get("format", "")).strip()
            if not relative_path or not format_name:
                issues.append(_issue("asset_export_invalid", requirement_id, "exported asset lacks format or local path", frame_id, asset_id, relative_path))
                continue
            tracked_paths.add(relative_path)
            file_issues = _validate_file(requirement_id, frame_id, asset_id, relative_path, format_name, asset, requirement_dir, relative_only=indexed)
            issues.extend(file_issues)
            mapped = indexed or (asset_id, relative_path) in mapping
            if not mapped:
                issues.append(_issue("asset_mapping_missing", requirement_id, "exported asset is absent from material mapping", frame_id, asset_id, relative_path))
            if mapped and not file_issues:
                successful_exports += 1
        if exportable_seen and successful_exports == 0:
            issues.append(_issue("reference_only_frame", requirement_id, "FRAME has independent assets but no mapped local export", frame_id))

    for mapped_node_id, mapped_path in sorted(mapping):
        if mapped_path not in tracked_paths:
            issues.append(_issue(
                "untracked_mapping_entry",
                requirement_id,
                "material mapping entry is absent from manifest",
                asset_node_id=mapped_node_id,
                path=mapped_path,
            ))

    assets_root = requirement_dir / "figma_assets"
    if assets_root.is_dir():
        for path in assets_root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in BUSINESS_EXTENSIONS:
                continue
            relative_path = path.relative_to(requirement_dir).as_posix()
            if relative_path not in tracked_paths:
                issues.append(_issue("untracked_asset_file", requirement_id, "business asset file is absent from manifest", path=relative_path))
    counts["missing"] = len(issues)
    return counts, issues


def audit_requirements(requirements_dir, requirement_id=None):
    requirements_dir = Path(requirements_dir)
    inventory = _load_inventory(requirements_dir)
    selected_ids = [requirement_id] if requirement_id else sorted(inventory)
    if requirement_id and requirement_id not in inventory:
        raise AuditInputError(f"requirement id not found in inventory: {requirement_id}")
    reports = []
    issues = []
    totals = {"requirements": 0, "frames": 0, "remote_reads": 0, "discovered_assets": 0, "required_assets": 0, "exported_assets": 0, "reused_assets": 0, "skipped_assets": 0, "missing": 0,
              "design_sources": 0, "legacy_manifests": 0}
    for current_id in selected_ids:
        counts, current_issues = _audit_requirement(requirements_dir, current_id, inventory[current_id])
        reports.append({"requirement_id": current_id, **counts})
        issues.extend(current_issues)
        totals["requirements"] += 1
        for key in counts:
            totals[key] += counts[key]
    issues.sort(key=lambda item: (item["requirement_id"], item["frame_node_id"], item["asset_node_id"], item["code"], item["path"]))
    totals["missing"] = len(issues)
    legacy = [report['requirement_id'] for report in reports if report['legacy_manifests']]
    return {"status": "passed" if not issues else "failed", "requirements": reports, "totals": totals, "issues": issues,
            "legacy_requirements": legacy,
            "limitations": ["Legacy schema 1/2 uses Markdown mappings; local design source integrity was not checked."] if legacy else []}


def _write_report(path, report):
    report_path = Path(path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Audit Agent-prepared Figma material completeness")
    parser.add_argument("--requirements-dir", required=True)
    parser.add_argument("--requirement-id")
    parser.add_argument("--report", required=True)
    args = parser.parse_args(argv)
    try:
        report = audit_requirements(args.requirements_dir, args.requirement_id)
        exit_code = 0 if report["status"] == "passed" else 1
    except (AuditInputError, OSError, ValueError, TypeError) as error:
        report = {"status": "error", "error": str(error), "requirements": [], "totals": {}, "issues": []}
        exit_code = 2
    _write_report(args.report, report)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

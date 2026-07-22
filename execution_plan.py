"""Stable JSON execution-plan storage for the break workflow."""

import hashlib
import json
import os

BLOCKED_STATUS = "阻塞"
BLOCKING_STATUS_MARKERS = ("阻塞", "阻断")


class ExecutionPlanStore:
    """Validate and persist the generated JSON projection of requirements/index.md."""

    def __init__(self, requirements_dir, index_file):
        self.requirements_dir = requirements_dir
        self.index_file = index_file
        self.plan_file = os.path.join(requirements_dir, "execution_plan.json")

    def index_hash(self):
        try:
            with open(self.index_file, "rb") as index_file:
                return hashlib.sha256(index_file.read()).hexdigest()
        except FileNotFoundError as error:
            raise ValueError(f"缺少需求索引: {self.index_file}") from error

    def is_current(self, valid_statuses):
        try:
            plan = self.read()
            changed = self.normalize_statuses(plan, valid_statuses)
            self.validate(plan, valid_statuses, self.index_hash())
            if changed:
                self.write(plan)
        except ValueError:
            return False
        return True

    def read(self):
        try:
            with open(self.plan_file, encoding="utf-8") as plan_file:
                return json.load(plan_file)
        except FileNotFoundError as error:
            raise ValueError(f"缺少执行计划: {self.plan_file}") from error
        except json.JSONDecodeError as error:
            raise ValueError(f"执行计划不是有效 JSON: {self.plan_file}") from error

    def write(self, plan):
        os.makedirs(self.requirements_dir, exist_ok=True)
        temporary_file = f"{self.plan_file}.tmp"
        with open(temporary_file, "w", encoding="utf-8") as plan_file:
            json.dump(plan, plan_file, ensure_ascii=False, indent=2)
            plan_file.write("\n")
        os.replace(temporary_file, self.plan_file)

    def set_status(self, requirement_id, status, valid_statuses, expected_source_hash=None):
        status = self.normalize_status(status, valid_statuses)
        if status not in valid_statuses:
            raise ValueError(f"未知需求状态: {status}")
        plan = self.read()
        self.normalize_statuses(plan, valid_statuses)
        self.validate(plan, valid_statuses, expected_source_hash)
        for item in plan["items"]:
            if item["id"] == requirement_id:
                item["status"] = status
                self.write(plan)
                return
        raise ValueError(f"找不到需求 ID: {requirement_id}")

    @staticmethod
    def normalize_status(status, valid_statuses):
        if not isinstance(status, str):
            return status
        normalized = status.strip()
        if normalized in valid_statuses:
            return normalized
        if BLOCKED_STATUS in valid_statuses and any(marker in normalized for marker in BLOCKING_STATUS_MARKERS):
            return BLOCKED_STATUS
        return normalized

    @staticmethod
    def normalize_statuses(plan, valid_statuses):
        if not isinstance(plan, dict) or not isinstance(plan.get("items"), list):
            return False
        changed = False
        for item in plan["items"]:
            if not isinstance(item, dict) or "status" not in item:
                continue
            normalized = ExecutionPlanStore.normalize_status(item["status"], valid_statuses)
            if normalized != item["status"]:
                item["status"] = normalized
                changed = True
        return changed

    @staticmethod
    def validate(plan, valid_statuses, expected_source_hash=None):
        if not isinstance(plan, dict) or plan.get("schema_version") != 1:
            raise ValueError("执行计划格式无效。")
        source_hash = plan.get("source_index_sha256")
        if not isinstance(source_hash, str) or len(source_hash) != 64 or any(
            character not in "0123456789abcdef" for character in source_hash.lower()
        ):
            raise ValueError("执行计划缺少有效的 index.md 哈希。")
        if expected_source_hash is not None and source_hash != expected_source_hash:
            raise ValueError("执行计划与当前 index.md 不一致。")
        if not isinstance(plan.get("items"), list) or not plan["items"]:
            raise ValueError("执行计划没有可执行条目。")
        required_fields = {
            "order": int,
            "id": str,
            "name": str,
            "status": str,
            "dependencies": list,
            "requirements_file": str,
            "acceptance_summary": str,
        }
        for item in plan["items"]:
            if not isinstance(item, dict):
                raise ValueError("执行计划条目格式无效。")
            for field, field_type in required_fields.items():
                if field not in item or type(item[field]) is not field_type:
                    raise ValueError(f"执行计划条目字段无效: {field}")
            normalized_status = ExecutionPlanStore.normalize_status(item["status"], valid_statuses)
            if normalized_status != item["status"]:
                item["status"] = normalized_status
            if item["order"] < 1 or not item["id"].strip() or not item["name"].strip():
                raise ValueError("执行计划条目缺少有效的顺序、ID 或名称。")
            if item["status"] not in valid_statuses:
                raise ValueError(f"未知需求状态: {item['status']}")
            if any(not isinstance(dependency, str) or not dependency.strip() for dependency in item["dependencies"]):
                raise ValueError("执行计划条目的前置依赖无效。")

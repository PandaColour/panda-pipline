"""Stable JSON execution-plan storage for the break workflow."""

import hashlib
import json
import os

BLOCKED_STATUS = "阻塞"
BLOCKING_STATUS_MARKERS = ("阻塞", "阻断")
DEMAND_STATUSES = {"拆分中", "拆分评审中", "需求分析中", "需求评审中", "开发中", "记忆整理中", "已完成", "阻塞"}
LEGACY_ITEM_STATUS_MAP = {
    "待需求分析": "需求分析中",
    "待需求评审": "需求评审中",
    "需求返工中": "需求分析中",
    "待实施": "待开发",
    "返工中": "开发中",
    "待记忆整理": "记忆整理中",
}


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
            changed = self.normalize_plan(plan, valid_statuses)
            self.validate(plan, valid_statuses, self.index_hash())
            if changed:
                self.write(plan)
        except ValueError as error:
            if "未知需求整体状态" in str(error):
                raise
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
        if isinstance(plan, dict):
            plan.pop("schema_version", None)
        temporary_file = f"{self.plan_file}.tmp"
        with open(temporary_file, "w", encoding="utf-8") as plan_file:
            json.dump(plan, plan_file, ensure_ascii=False, indent=2)
            plan_file.write("\n")
        os.replace(temporary_file, self.plan_file)

    def set_status(self, requirement_id, status, valid_statuses, expected_source_hash=None):
        self.set_item_status(requirement_id, status, valid_statuses, expected_source_hash)

    def set_item_status(self, requirement_id, status, valid_statuses, expected_source_hash=None):
        status = self.normalize_status(status, valid_statuses)
        if status not in valid_statuses:
            raise ValueError(f"未知需求状态: {status}")
        plan = self.read()
        self.normalize_plan(plan, valid_statuses)
        self.validate(plan, valid_statuses, expected_source_hash)
        for item in plan["items"]:
            if item["id"] == requirement_id:
                item["status"] = status
                self.write(plan)
                return
        raise ValueError(f"找不到需求 ID: {requirement_id}")

    def set_demand_status(self, status, source=None):
        status = self.normalize_demand_status(status)
        if status not in DEMAND_STATUSES:
            raise ValueError(f"未知需求整体状态: {status}")
        try:
            plan = self.read()
        except ValueError:
            plan = {"demand": {"id": "D-001", "status": status, "source": source or ""}, "items": []}
        self._ensure_demand(plan)
        plan["demand"]["status"] = status
        if source is not None:
            plan["demand"]["source"] = source
        self.write(plan)

    def set_pending_feedback(self, requirement_id, *, kind, source_status, message):
        plan = self.read()
        self.normalize_plan(plan, None)
        for item in plan.get("items", []):
            if item.get("id") == requirement_id:
                item["pending_feedback"] = {
                    "kind": kind,
                    "source_status": source_status,
                    "message": message,
                }
                self.write(plan)
                return
        raise ValueError(f"找不到需求 ID: {requirement_id}")

    def clear_pending_feedback(self, requirement_id):
        plan = self.read()
        self.normalize_plan(plan, None)
        for item in plan.get("items", []):
            if item.get("id") == requirement_id:
                item["pending_feedback"] = None
                self.write(plan)
                return
        raise ValueError(f"找不到需求 ID: {requirement_id}")

    def get_pending_feedback(self, requirement_id):
        plan = self.read()
        self.normalize_plan(plan, None)
        for item in plan.get("items", []):
            if item.get("id") == requirement_id:
                return item.get("pending_feedback")
        raise ValueError(f"找不到需求 ID: {requirement_id}")

    def set_agent_session(self, agent_name, *, session_id, prompt_file, agent_type, requirement_id=None):
        if not isinstance(agent_name, str) or not agent_name.strip():
            raise ValueError("Agent 名称无效。")
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValueError("Agent session_id 无效。")
        plan = self.read()
        self.normalize_plan(plan, None)
        target = self._agent_session_target(plan, requirement_id)
        sessions = target.setdefault("agent_sessions", {})
        sessions[agent_name] = {
            "session_id": session_id,
            "prompt_file": prompt_file,
            "agent_type": agent_type,
        }
        self.write(plan)

    def get_agent_session(self, agent_name, *, requirement_id=None):
        plan = self.read()
        self.normalize_plan(plan, None)
        targets = []
        if requirement_id:
            targets.append(self._agent_session_target(plan, requirement_id))
        targets.append(plan.get("demand", {}))
        if not requirement_id:
            targets.extend(item for item in plan.get("items", []) if isinstance(item, dict))
        for target in targets:
            sessions = target.get("agent_sessions") if isinstance(target, dict) else None
            if not isinstance(sessions, dict):
                continue
            record = sessions.get(agent_name)
            if isinstance(record, str):
                return record
            if isinstance(record, dict) and isinstance(record.get("session_id"), str):
                return record["session_id"]
        return None

    @staticmethod
    def _agent_session_target(plan, requirement_id=None):
        if requirement_id is None:
            return plan["demand"]
        for item in plan.get("items", []):
            if isinstance(item, dict) and item.get("id") == requirement_id:
                return item
        raise ValueError(f"找不到需求 ID: {requirement_id}")

    @staticmethod
    def normalize_status(status, valid_statuses):
        if not isinstance(status, str):
            return status
        normalized = status.strip()
        normalized = LEGACY_ITEM_STATUS_MAP.get(normalized, normalized)
        if any(marker in normalized for marker in BLOCKING_STATUS_MARKERS):
            return BLOCKED_STATUS
        if valid_statuses is None:
            return normalized
        if normalized in valid_statuses:
            return normalized
        return normalized

    @staticmethod
    def normalize_demand_status(status):
        if not isinstance(status, str):
            return status
        normalized = status.strip()
        if any(marker in normalized for marker in BLOCKING_STATUS_MARKERS):
            return BLOCKED_STATUS
        return normalized

    @staticmethod
    def normalize_plan(plan, valid_statuses):
        if not isinstance(plan, dict):
            return False
        changed = False
        if "schema_version" in plan:
            del plan["schema_version"]
            changed = True
        if ExecutionPlanStore._ensure_demand(plan):
            changed = True
        demand_status = ExecutionPlanStore.normalize_demand_status(plan["demand"].get("status"))
        if demand_status != plan["demand"].get("status"):
            plan["demand"]["status"] = demand_status
            changed = True
        if ExecutionPlanStore.normalize_statuses(plan, valid_statuses):
            changed = True
        for item in plan.get("items", []):
            if isinstance(item, dict) and "pending_feedback" not in item:
                item["pending_feedback"] = None
                changed = True
        return changed

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
        if not isinstance(plan, dict):
            raise ValueError("执行计划格式无效。")
        demand = plan.get("demand")
        if not isinstance(demand, dict):
            raise ValueError("执行计划缺少需求整体状态。")
        if not isinstance(demand.get("id"), str) or not demand["id"].strip():
            raise ValueError("执行计划缺少有效的需求整体 ID。")
        if not isinstance(demand.get("source"), str):
            raise ValueError("执行计划缺少有效的需求来源。")
        demand_status = ExecutionPlanStore.normalize_demand_status(demand.get("status"))
        if demand_status != demand.get("status"):
            demand["status"] = demand_status
        if demand["status"] not in DEMAND_STATUSES:
            raise ValueError(f"未知需求整体状态: {demand['status']}")
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
            if "pending_feedback" in item and item["pending_feedback"] is not None:
                feedback = item["pending_feedback"]
                if not isinstance(feedback, dict):
                    raise ValueError("执行计划条目的待处理反馈无效。")
                for field in ("kind", "source_status", "message"):
                    if not isinstance(feedback.get(field), str):
                        raise ValueError(f"执行计划条目的待处理反馈字段无效: {field}")

    @staticmethod
    def _ensure_demand(plan):
        if not isinstance(plan, dict):
            return False
        if isinstance(plan.get("demand"), dict):
            demand = plan["demand"]
            changed = False
            if "id" not in demand:
                demand["id"] = "D-001"
                changed = True
            if "status" not in demand:
                demand["status"] = ExecutionPlanStore._derive_demand_status(plan)
                changed = True
            if "source" not in demand:
                demand["source"] = ""
                changed = True
            return changed
        plan["demand"] = {
            "id": "D-001",
            "status": ExecutionPlanStore._derive_demand_status(plan),
            "source": "",
        }
        return True

    @staticmethod
    def _derive_demand_status(plan):
        items = plan.get("items")
        if not isinstance(items, list) or not items:
            return "拆分中"
        statuses = {
            ExecutionPlanStore.normalize_status(item.get("status"), None)
            for item in items
            if isinstance(item, dict)
        }
        if statuses and statuses <= {"已完成"}:
            return "已完成"
        if BLOCKED_STATUS in statuses:
            return "阻塞"
        if "记忆整理中" in statuses:
            return "记忆整理中"
        return "开发中"

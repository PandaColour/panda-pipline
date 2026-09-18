"""File-only task handoff and bounded machine-readable final receipts."""

import hashlib
import json
import re
from pathlib import Path

MAX_FINAL_CHARS = 2048
FINAL_MARKER_PATTERN = r'(?<!\w)FINAL_ANSWER(?=[\s:{])'
FINAL_INSTRUCTION = (
    '先读取指定输入，完成本轮明确任务；详细分析、完整问题清单、测试证据和修改建议写入输出文档。'
    '返回前确认必需输出已写入。最终只输出 FINAL_ANSWER 后跟一个 JSON 对象，'
    '含标记在内不超过 2048 字符（中文按字符，不按字节）；不要凑满。'
    '必填 status、summary（非空字符串）、outputs（名称到路径的对象）。'
    'approval_token 仅为可选补充说明，可省略、为 null 或空字符串，不参与流程判定。'
    'summary 仅简短结论；不返回 issues 正文。分析/开发/整理完成用 completed；'
    '评审按本轮允许状态返回，通过用 approved；流程仅依据当前阶段允许的 status 和产物校验推进。'
    '路径相对明确的项目根目录解析。过程日志不是最终回执。'
)


class ReceiptError(RuntimeError):
    kind = 'receipt_format_error'


class TaskRetryRequired(Exception):
    """Task state is saved; exit so the wrapper can restart the pipeline."""


class ReceiptPending(TaskRetryRequired):
    """A producer needs receipt-only recovery, not another execution."""


class TaskMessage(str):
    def __new__(cls, task, inputs, outputs, requirements, statuses, *, root=None, optional_outputs=()):
        data = dict(task=task, project_root=str(root or Path.cwd()),
                    inputs=list(inputs), outputs=list(outputs), optional_outputs=list(optional_outputs),
                    allowed_statuses=sorted(statuses))
        message = ('当前任务与文档路径：\n' + json.dumps(data, ensure_ascii=False, indent=2)
                   + '\n执行要求：\n' + requirements + '\n最终回执：\n' + FINAL_INSTRUCTION)
        obj = super().__new__(cls, message)
        obj.outputs = list(outputs)
        obj.optional_outputs = list(optional_outputs)
        obj.statuses = set(statuses)
        return obj


def parse_final_answer(response):
    if not isinstance(response, str):
        raise ReceiptError('缺少 FINAL_ANSWER')
    # Some CLI streams concatenate separate assistant messages without a newline.
    # Extract a complete receipt even when progress or a closing summary surrounds
    # it. Never infer success from prose or repair incomplete JSON.
    markers = list(re.finditer(FINAL_MARKER_PATTERN, response))
    if not markers:
        raise ReceiptError('缺少 FINAL_ANSWER')
    error = None
    for marker in reversed(markers):
        try:
            return _parse_final_suffix(response[marker.start():])
        except ReceiptError as caught:
            error = caught
    raise error


def _parse_final_suffix(response):
    final = response.strip()
    body = final[len('FINAL_ANSWER'):].lstrip().removeprefix(':').lstrip()
    fence = re.match(r'```(?:json)?[ \t]*\r?\n', body)
    if fence:
        body = body[fence.end():].lstrip()
    try:
        result, end = json.JSONDecoder().raw_decode(body)
    except (ValueError, TypeError) as error:
        raise ReceiptError('FINAL_ANSWER 必须是单个完整 JSON 对象') from error
    if not isinstance(result, dict):
        raise ReceiptError('FINAL_ANSWER 必须是 JSON 对象')
    # Bound the extracted receipt, not unrelated CLI progress/closing prose.
    size = len('FINAL_ANSWER\n') + end
    if size > MAX_FINAL_CHARS:
        raise ReceiptError(f'FINAL_ANSWER 超过 {MAX_FINAL_CHARS} 字符（实际 {size}）')
    tail = body[end:].lstrip()
    if fence:
        if not tail.startswith('```'):
            raise ReceiptError('FINAL_ANSWER JSON 代码围栏未闭合')
        tail = tail[3:].lstrip()
    # Do not treat a second payload or a later broken receipt as closing prose.
    if tail.startswith(('{', '[', '```')) or re.search(FINAL_MARKER_PATTERN, tail):
        raise ReceiptError('FINAL_ANSWER 后存在额外 JSON 或回执')
    return result


def validate_receipt(response, task, root):
    result = parse_final_answer(response)
    if not isinstance(result.get('status'), str) or result['status'] not in task.statuses:
        raise ReceiptError('status 不属于当前阶段允许值')
    if not isinstance(result.get('summary'), str):
        raise ReceiptError('缺少字符串字段 summary')
    if not result['summary'].strip():
        raise ReceiptError('summary 不能为空')
    if result.get('issues'):
        raise ReceiptError('完整 issues 必须写入报告，不得放进回执')
    outputs = result.get('outputs')
    if not isinstance(outputs, dict) or not all(isinstance(v, str) and v.strip() for v in outputs.values()):
        raise ReceiptError('outputs 必须是名称到文件路径的对象')
    def resolve(value):
        try:
            return (Path(root) / value).resolve()
        except (ValueError, OSError) as error:
            raise ReceiptError('输出路径无法解析') from error
    declared = {resolve(p) for p in task.outputs + task.optional_outputs}
    reported = {resolve(p) for p in outputs.values()}
    if not reported <= declared:
        raise ReceiptError('回执包含未声明的输出路径')
    if result['status'] != 'blocked' and not {resolve(p) for p in task.outputs} <= reported:
        raise ReceiptError('回执缺少必需输出文档路径')
    try:
        if any(not p.is_file() for p in reported):
            raise ReceiptError('回执声明的输出文件不存在')
    except (ValueError, OSError) as error:
        raise ReceiptError('输出路径无法检查') from error
    if result['status'] == 'blocked':
        read_resource_blocker(result, root)
    final = 'FINAL_ANSWER\n' + json.dumps(result, ensure_ascii=False, separators=(',', ':'))
    if len(final) > MAX_FINAL_CHARS:
        raise ReceiptError('规范化后的 FINAL_ANSWER 超长')
    return final


def read_resource_blocker(result, root):
    value = result.get('outputs', {}).get('blocker')
    if not isinstance(value, str):
        raise ReceiptError('blocked 回执缺少 outputs.blocker')
    path = (Path(root) / value).resolve()
    if not path.is_relative_to((Path(root) / 'requirements').resolve()) or path.name != 'resource_blocker.json':
        raise ReceiptError('资源阻塞报告必须位于 requirements 内的指定 resource_blocker.json')
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as error:
        raise ReceiptError('资源阻塞报告不存在或不是 JSON') from error
    if (not isinstance(data, dict) or not isinstance(data.get('kind'), str)
            or data['kind'] not in {'file_unreadable', 'material_permission_denied'}):
        raise ReceiptError('资源阻塞类型无效')
    if not all(isinstance(data.get(k), str) and data[k].strip() for k in ('resource', 'reason', 'impact', 'required_user_action')):
        raise ReceiptError('资源阻塞报告缺少原始资源、原因、影响或用户动作')
    return data


def save_handoff(directory, name, content):
    """Immutable, content-deduplicated handoff within its owning directory."""
    text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False, indent=2)
    encoded = text.encode('utf-8')
    digest = hashlib.sha256(encoded).hexdigest()
    path = Path(directory) / 'handoffs' / f'{name}-{digest}.txt'
    path.parent.mkdir(parents=True, exist_ok=True)
    # ReviewContext and the scheduler may label the same receipt differently.
    # Reuse the existing snapshot; never move files referenced by older tasks.
    for existing in sorted(path.parent.glob(f'*-{digest}.txt')):
        if existing.is_file() and existing.read_bytes() == encoded:
            return str(existing.resolve())
    if not path.exists():
        path.write_bytes(encoded)
    return str(path.resolve())


def failure_kind(error):
    if isinstance(error, ReceiptError):
        return error.kind
    text = str(error).lower()
    if any(s in text for s in ('argument list too long', 'no such file', 'executable', 'errno 7', 'permission denied')):
        return 'startup_error'
    if any(s in text for s in ('network', 'connection', 'timeout', 'timed out', 'dns', 'fetch failed')):
        return 'network_error'
    return 'execution_error'

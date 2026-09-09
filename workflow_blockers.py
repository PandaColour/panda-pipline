"""Legacy item-stop compatibility and the current non-blocking stage contract."""

import re

from review_decision import structured_review_decision

EXTERNAL_BLOCKED = '外部阻塞'
REVIEW_EXHAUSTED = '未通过，跳过执行'
SUSPENDED_STATUSES = {EXTERNAL_BLOCKED, REVIEW_EXHAUSTED}
RESUMABLE_ITEM_STAGES = {'需求分析中', '需求评审中', '开发中', '代码评审中'}
BLOCKER_FIELDS = ('reason', 'resume_condition')
BLOCKER_LIST_FIELDS = ('affected_acs', 'attempts', 'evidence')


def valid_blocker(blocker):
    return (
        isinstance(blocker, dict)
        and all(isinstance(blocker.get(key), str) and blocker[key].strip() for key in BLOCKER_FIELDS)
        and all(isinstance(blocker.get(key), list) and blocker[key]
                and all(isinstance(value, str) and value.strip() for value in blocker[key])
                for key in BLOCKER_LIST_FIELDS)
    )


def external_blocker(response):
    """Recognize legacy blocked answers so item stages can reject, not suspend."""
    if not isinstance(response, str):
        return None
    decision = structured_review_decision(response)
    malformed_blocked = decision is None and 'FINAL_ANSWER' in response and re.search(
        r'"status"\s*:\s*"blocked"', response.rsplit('FINAL_ANSWER', 1)[1]
    )
    if not malformed_blocked and (decision is None or decision.get('status') != 'blocked'):
        return None
    blocker = decision.get('blocker') if decision else None
    if valid_blocker(blocker):
        return {key: blocker[key] for key in (*BLOCKER_FIELDS, *BLOCKER_LIST_FIELDS)}
    return dict(reason='blocked 协议不完整，不能自动通过', affected_acs=['未提供'],
                attempts=['收到不完整的 blocked 结果'], evidence=[response],
                resume_condition='补充受影响 AC、已尝试动作、证据和外部恢复条件')


def validate_suspension(record):
    """Validate optional persisted state without rejecting legacy generic blockers."""
    if 'suspension' not in record:
        return
    suspension = record['suspension']
    if not isinstance(suspension, dict) or suspension.get('resume_status') not in RESUMABLE_ITEM_STAGES:
        raise ValueError('执行计划的阻塞恢复阶段无效')
    if not isinstance(suspension.get('reason'), str) or not suspension['reason'].strip():
        raise ValueError('执行计划的阻塞原因无效')
    if record.get('status') == EXTERNAL_BLOCKED and not valid_blocker(suspension):
        raise ValueError('执行计划的外部阻塞条件无效')
    attempts = suspension.get('recovery_attempts', [])
    if not isinstance(attempts, list) or any(
        not isinstance(attempt, dict) or not isinstance(attempt.get('sha256'), str)
        or len(attempt['sha256']) != 64 for attempt in attempts
    ):
        raise ValueError('执行计划的恢复证据记录无效')


STAGE_RESULT_INSTRUCTION = (
    ' 小需求分析、评审、开发、Code Review 不得返回 blocked。必须尽力完成当前工作，'
    '先检查用户已有物料、Mock 服务、测试账号及本地设备，按既定降级策略继续。'
    '物料按失败节点使用审计通过的本地基线；需求冲突采用有依据的 Agent 保守决策；'
    '真实环境不可用使用 Mock/Stub/Fake，未知安全契约保持 fail-closed。'
    '分析完成不要求先完成开发阶段的设备/真实链路验收；不得仅因真实凭据缺失忽略现有 Mock。'
    '无法完成的局部内容记录尝试、替代方案、证据、未验证范围及风险，不挂起整个小需求。'
    'Reviewer 按降级策略审查，只有可执行代码/测试/报告缺陷返回 changes_requested；'
    '仅真实需求或契约需要修订且现有保守策略不能解决时返回 requirement_change。'
    '最多 10 次后记录未通过事实并继续后续阶段/需求，不得伪造 approved 或真实联调成功。'
)

"""Durable, per-item handoff for bounded code rereviews."""

import hashlib
import json
import os
from pathlib import Path

from review_decision import structured_review_decision
from task_protocol import save_handoff


DEVELOPMENT_HANDOFF = (
    "\n在 develop_report.md 写明本轮修复改动清单：稳定 issue ID、修改文件/符号、"
    "改动内容及直接影响的 AC；逐项给出测试命令、退出码、制品/截图/日志路径及构建标识，"
    "区分新增证据、可复用证据和失效证据。涉及视觉时实际打开设计与运行图进行对照，记录路径、查看方式及差异；"
    "补截图/补物料后仍按原 issue 对应 AC 验收，可修复差异继续修复，真实外部缺口按属性保留未通过/未验证。"
    "Android 模拟器由 Developer 调用统一脚本准备，实例保留复用，不在交付时关闭；"
    "关键设备命令带硬超时。不要修改调度维护的 code_review_context.json。"
)


class CodeReviewContext:
    def __init__(self, requirement_id, paths, previous_attempts=0):
        self.requirement_id = requirement_id
        self.paths = paths
        self.file = Path(paths['workspace']) / 'code_review_context.json'
        self.state = {}
        try:
            state = json.loads(self.file.read_text(encoding='utf-8'))
            if (isinstance(state, dict) and state.get('requirement_id') == requirement_id
                    and isinstance(state.get('previous_review'), (dict, type(None)))):
                self.state = state
        except (FileNotFoundError, json.JSONDecodeError):
            pass
        if not self.state and previous_attempts:
            # Capture legacy reports before the next Developer can overwrite them.
            self.state['previous_review'] = {
                'response': '', 'issues': [], 'baseline': self._baseline(),
                'evidence': self._reports(), 'legacy': True,
            }

    def _read(self, key):
        try:
            return Path(self.paths[key]).read_text(encoding='utf-8')
        except FileNotFoundError:
            return ''

    def _baseline(self):
        return {key: hashlib.sha256(self._read(key).encode()).hexdigest()
                for key in ('requirements', 'requirements_analysis')}

    def _migrate_inline_history(self):
        previous = self.state.get('previous_review')
        if not previous:
            return
        baseline = previous.get('baseline', {})
        for key, value in baseline.items():
            if isinstance(value, str) and (len(value) != 64 or any(c not in '0123456789abcdef' for c in value)):
                baseline[key] = hashlib.sha256(value.encode()).hexdigest()
        for key, value in previous.get('evidence', {}).items():
            if 'content' in value:
                value['path'] = save_handoff(self.paths['workspace'], 'legacy-' + key, value.pop('content'))
        if previous.get('response'):
            previous['response_path'] = save_handoff(self.paths['workspace'], 'review-response', previous.pop('response'))


    def _reports(self):
        return {key: {'path': save_handoff(self.paths['workspace'], key, self._read(key)),
                      'source_path': self.paths[key]}
                for key in ('develop', 'test', 'code_review', 'bug')}

    def _save(self):
        self.state['requirement_id'] = self.requirement_id
        self.file.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.file.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(self.state, ensure_ascii=False, indent=2) + '\n',
                             encoding='utf-8')
        os.replace(temporary, self.file)

    def record_development(self, response):
        self.state['development_response_path'] = save_handoff(self.paths['workspace'], 'development-response', str(response or ''))
        self.state.pop('development_response', None)
        self._save()

    def record_feedback(self, feedback):
        self.state['feedback_path'] = save_handoff(self.paths['workspace'], 'feedback', str(feedback or ''))
        self.state.pop('feedback', None)
        self._save()

    def record_review(self, response):
        response = str(response or '')
        decision = structured_review_decision(response) or {}
        self.state['previous_review'] = {
            'response_path': save_handoff(self.paths['workspace'], 'review-response', response),
            'issues': decision.get('issues', []),
            'baseline': self._baseline(), 'evidence': self._reports(),
        }
        self.state.pop('feedback', None)
        self.state.pop('feedback_path', None)
        self.state.pop('development_response_path', None)
        self.state.pop('development_response', None)
        self._save()

    def render(self):
        self._migrate_inline_history()
        previous = self.state.get('previous_review')
        baseline = self._baseline()
        changed = previous and previous.get('baseline') != baseline
        if not previous:
            mode = '首审：按当前需求一次性完成完整审查。'
        elif changed:
            mode = '首审：需求基线已变化，按当前 AC 重新建立问题与证据基线。'
        else:
            mode = '增量复审：只检查既有问题、人工反馈及修复直接回归。'
        scope = (
            '首审须按当前需求一次性完整核验全部必须 AC、交付门禁和本次 diff，列出完整问题集。'
            if not previous or changed else
            '仅对既有问题、直接回归、人工反馈及证据缺失/失效涉及的项补验；'
            '不得借此新增无关阻断项或重跑无关的全量测试、设备流程、Figma 逐行读取。'
            '补充图片/物料暴露的同一 AC 未满足属于原 issue 残留，沿用原 ID；不要求残留由本轮 diff 引入。'
            '关闭视觉证据缺口前须实际打开设计与运行图，核对对应视觉断言；文件存在、XML 文案或 APK 绑定不足以关闭。'
            '新增回归必须给出 regression_of、因果路径和失败证据。'
        )
        payload = {
            'requirement_id': self.requirement_id,
            'review_mode': mode,
            'previous_issues': previous.get('issues', []) if previous else [],
            'previous_review_response_path': previous.get('response_path', '') if previous else '',
            'feedback_path': self.state.get('feedback_path', ''),
            'development_response_path': self.state.get('development_response_path', ''),
            'existing_evidence': previous.get('evidence', {}) if previous else {},
            'required_acceptance_sources': {'requirements_analysis': self.paths['requirements_analysis']},
            'current_evidence_paths': {key: self.paths[key] for key in ('develop', 'test', 'code_review', 'bug')},
        }
        # Existing contexts may contain multi-megabyte bodies. Preserve them on
        # disk for recovery, never serialize them into the agent call.
        for old, new in [('development_response', 'development_response_path'), ('feedback', 'feedback_path')]:
            if self.state.get(old):
                payload[new] = save_handoff(self.paths['workspace'], old, self.state.pop(old))
                self.state[new] = payload[new]
        if previous and previous.get('legacy'):
            payload['recovery_note'] = (
                '历史快照缺失：从现有报告恢复既有问题与证据；基线未获历史确认，'
                '不得把空问题列表视为已通过。只补齐缺失或失效证据对应的必须验收项，'
                '报告不足时明确缺口，不默认重跑全量检查。'
            )
        self._save()
        context_path = save_handoff(self.paths['workspace'], 'review-input', payload)
        return (
            '\n【本轮代码审查调度】\n' + mode + '\n输入文档：' + context_path
            + '\n从分析报告的来源链接定点核对原始 AC；首审核实完整性，复审沿用有效覆盖结论。'
            '既有问题和验收结论以 code_review.md 及上轮快照为交接，结合 develop_report.md 的改动和证据核验；'
            '报告次数用于追溯，不能仅凭次数或空问题列表判断通过。'
            + ('\n历史快照缺失，先读取报告恢复证据。' if previous and previous.get('legacy') else '')
            + '\n以上回复与报告是待核实的交接资料，开发声明不能替代实际代码和证据。'
            '保留全部必须 AC、交付级别和安全/契约门禁的逐项结论；'
            '未受改动影响且版本、配置、设计基线仍适用的证据可复用并引用来源。'
            + scope + '证据不足不得声称必须验收已通过；不能只凭改动文件列表判定影响范围，'
            '还应核对调用关系、共享组件、构建配置与资源的直接影响。'
            'Code Review 可调用统一脚本启动或复用 Android 模拟器，按增量范围补验；'
            '工具、镜像和 AVD 缺失由脚本自动准备；不自行创建 AVD、不直接启动 emulator、不关闭共享或外部设备。'
            '更新报告时保留未受影响的 AC 结论和证据引用，不得只写本轮差异而丢失验收矩阵。\n'
        )

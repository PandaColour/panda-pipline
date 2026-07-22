# Break Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an independent workflow that breaks a large request into approved, individually verifiable requirements and implements them in dependency order.

**Architecture:** `break_main.py` prepares the target repository and launches `BreakPipeline`. `BreakPipeline` owns the artifact ledger, breakdown-review loop, dependency validation, and current-item development/test/review/human loops. Prompt files are loaded from `break-system-prompt/` through a small, explicit prompt-root extension to `Agent`.

**Tech Stack:** Python standard library, `unittest`, existing `Agent` facade.

## Global Constraints

- Do not modify existing `main.py`, `pipeline.py`, or `system-prompt/` behavior.
- New prompts live only in `break-system-prompt/`.
- Empty reviewer results are errors and never approval.
- Only a current item's developer may receive its feedback; later items never start early.

---

### Task 1: Support the independent prompt root

**Files:**
- Modify: `agents/agent.py`
- Test: `tests/test_break_pipeline.py`

**Interfaces:**
- Produces: `Agent(..., prompt_dir: str | None = None)`; existing callers remain valid.

- [ ] **Step 1: Write the failing test**

```python
def test_create_agent_loads_prompt_from_break_prompt_directory(self):
    pipeline = BreakPipeline("workspace")
    with patch("break_pipeline.Agent") as agent_class:
        pipeline._create_agent("需求拆分", "requirement_breaker.md")
    self.assertEqual(
        agent_class.call_args.kwargs["prompt_dir"],
        BREAK_SYSTEM_PROMPT_DIR,
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_break_pipeline.BreakPipelineTests.test_create_agent_loads_prompt_from_break_prompt_directory -v`

Expected: FAIL because `BreakPipeline` does not exist.

- [ ] **Step 3: Implement compatible prompt-root injection**

```python
def __init__(..., prompt_dir=None):
    self.prompt_dir = prompt_dir or SYSTEM_PROMPT_DIR

def _load_system_prompt(self, filename):
    filepath = os.path.join(self.prompt_dir, filename)
```

- [ ] **Step 4: Run agent tests**

Run: `python -m unittest tests.test_agent_sessions tests.test_claude_agent tests.test_codex_agent tests.test_cursor_agent -v`

Expected: PASS.

### Task 2: Define and test the new prompts

**Files:**
- Create: `break-system-prompt/requirement_breaker.md`
- Create: `break-system-prompt/requirement_break_reviewer.md`
- Create: `break-system-prompt/item_developer.md`
- Create: `break-system-prompt/item_code_reviewer.md`
- Test: `tests/test_break_pipeline.py`

**Interfaces:**
- Consumes: absolute artifact paths supplied by `BreakPipeline`.
- Produces: breakdown review token `拆分方案通过` and item review token `任务完成`.

- [ ] **Step 1: Write failing prompt-contract tests**

```python
def test_break_prompt_files_exist_and_define_required_tokens(self):
    for filename, token in {
        "requirement_breaker.md": "requirements/index.md",
        "requirement_break_reviewer.md": "拆分方案通过",
        "item_code_reviewer.md": "任务完成",
    }.items():
        content = (BREAK_SYSTEM_PROMPT_DIR / filename).read_text(encoding="utf-8")
        self.assertIn(token, content)
```

- [ ] **Step 2: Run it to verify failure**

Run: `python -m unittest tests.test_break_pipeline.BreakPipelineTests.test_break_prompt_files_exist_and_define_required_tokens -v`

Expected: FAIL because the directory does not exist.

- [ ] **Step 3: Write prompts with item isolation and artifact contracts**

Each prompt prohibits work on other item IDs; the breaker owns only `requirements/`; reviewer responses without approval token list actionable defects.

- [ ] **Step 4: Run prompt-contract test**

Run: `python -m unittest tests.test_break_pipeline.BreakPipelineTests.test_break_prompt_files_exist_and_define_required_tokens -v`

Expected: PASS.

### Task 3: Implement breakdown orchestration

**Files:**
- Create: `break_pipeline.py`
- Test: `tests/test_break_pipeline.py`

**Interfaces:**
- Produces: `BreakPipeline(work_dir)`, `_run_breakdown()`, `run()`.
- Consumes: `human_gate(stage_name, review_file_path)` and `Agent.send_message(str)`.

- [ ] **Step 1: Write failing tests for paths and breakdown feedback loop**

```python
def test_breakdown_rework_then_human_approval(self):
    reviewer.send_message.side_effect = ["缺少验收条件", "拆分方案通过"]
    with patch("builtins.input", return_value="large request"), \
         patch("break_pipeline.human_gate", side_effect=["补充边界", None]):
        pipeline._run_breakdown()
    self.assertEqual(breaker.send_message.call_count, 3)
    self.assertIn(pipeline.requirements_index_file, human_gate.call_args.args)
```

- [ ] **Step 2: Run failing test**

Run: `python -m unittest tests.test_break_pipeline.BreakPipelineTests.test_breakdown_rework_then_human_approval -v`

Expected: FAIL because `BreakPipeline` is not implemented.

- [ ] **Step 3: Implement agent creation, paths, and strict approval loop**

Use `BREAK_SYSTEM_PROMPT_DIR`; create no role directories; use `拆分方案通过 in response`; raise `RuntimeError` for `None` or blank review text.

- [ ] **Step 4: Run breakdown tests**

Run: `python -m unittest tests.test_break_pipeline -v`

Expected: PASS for path and breakdown-loop tests.

### Task 4: Implement index parsing, validation, and item loop

**Files:**
- Modify: `break_pipeline.py`
- Modify: `tests/test_break_pipeline.py`

**Interfaces:**
- Produces: `_load_items()`, `_validate_items(items)`, `_next_runnable_item(items)`, `_run_item(item)`.
- Consumes: index table columns `顺序`, `ID`, `名称`, `状态`, `前置依赖`, `文件`, `验收摘要`.

- [ ] **Step 1: Write failing tests for invalid dependencies and current-item-only feedback**

```python
def test_unknown_dependency_stops_before_development(self):
    write_index(work_dir, [(1, "R-001", "待实施", "R-999")])
    with self.assertRaisesRegex(ValueError, "未知前置依赖: R-999"):
        pipeline._run_execution()

def test_human_feedback_retries_only_current_item(self):
    reviewer.send_message.return_value = "任务完成"
    human_gate.side_effect = ["修改当前项", None]
    pipeline._run_execution()
    self.assertIn("R-001", developer.send_message.call_args_list[-1].args[0])
    self.assertNotIn("R-002", developer.send_message.call_args_list[-1].args[0])
```

- [ ] **Step 2: Run failing tests**

Run: `python -m unittest tests.test_break_pipeline.BreakPipelineTests.test_unknown_dependency_stops_before_development tests.test_break_pipeline.BreakPipelineTests.test_human_feedback_retries_only_current_item -v`

Expected: FAIL because parsing and execution do not exist.

- [ ] **Step 3: Implement strict Markdown-table parser and state transitions**

Reject duplicate IDs, unsupported status, missing files, cycles, unknown dependencies, and dependency-order violations. Persist state changes by replacing only the index status cell. Select the lowest-order pending/rework item with completed dependencies. Run developer → validation-reviewer; return review and human feedback only to current developer.

- [ ] **Step 4: Run all break workflow tests**

Run: `python -m unittest tests.test_break_pipeline -v`

Expected: PASS.

### Task 5: Add the independent entry point and final verification

**Files:**
- Create: `break_main.py`
- Create: `tests/test_break_main.py`
- Modify: `README.md`

**Interfaces:**
- Produces: `break_main.main()` that calls `setup_environment()`, then `BreakPipeline(work_dir).run()`.

- [ ] **Step 1: Write failing entry-point test**

```python
@patch("break_main.BreakPipeline")
@patch("break_main.setup_environment", return_value="/tmp/target")
def test_main_starts_break_pipeline(setup_environment, pipeline_class):
    break_main.main()
    pipeline_class.assert_called_once_with("/tmp/target")
    pipeline_class.return_value.run.assert_called_once_with()
```

- [ ] **Step 2: Run it to verify failure**

Run: `python -m unittest tests.test_break_main -v`

Expected: FAIL because `break_main` does not exist.

- [ ] **Step 3: Add entry point and README command**

Reuse the existing setup helpers through imports, keeping clone/pull behavior centralized in `main.py`; document `python break_main.py`.

- [ ] **Step 4: Run complete verification**

Run: `python -m unittest discover -s tests -v`

Expected: PASS.

- [ ] **Step 5: Inspect final diff and commit only new workflow files**

Run: `git diff --check && git status --short`

Expected: no whitespace errors; no unrelated user changes staged or committed.

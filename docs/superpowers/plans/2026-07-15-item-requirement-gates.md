# Item Requirement Gates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Require every split item to pass analysis, requirements review, and requirements human approval before development.

**Architecture:** Extend `BreakPipeline` with two item-level requirement agents and a state-machine branch preceding `_run_item`. Requirement-change feedback returns to that branch; implementation-only feedback stays in the existing implementation loop.

**Tech Stack:** Python standard library and `unittest`.

## Global Constraints

- Do not change the original `pipeline.py` behavior.
- Only the current item may be changed by item requirement agents.
- A requirements human gate is mandatory before `待实施`.

---

### Task 1: Define item requirement agent contracts

**Files:** Create `break-system-prompt/item_requirements_analyst.md`; create `break-system-prompt/item_requirements_reviewer.md`; modify `break-system-prompt/requirement_breaker.md`; test `tests/test_break_pipeline.py`.

- [ ] Write tests asserting the new prompts and `同意方案` contract exist, run `python3 -m unittest tests.test_break_pipeline -v` and observe failure.
- [ ] Add prompts and require initial index status `待需求分析`.
- [ ] Re-run the test command and observe PASS.

### Task 2: Implement requirements state machine

**Files:** Modify `break_pipeline.py`; modify `tests/test_break_pipeline.py`.

- [ ] Write tests that a current item runs analyst → reviewer → requirements human gate before developer, and that reviewer feedback retries only analyst.
- [ ] Run the targeted tests and observe failure.
- [ ] Add statuses, `_run_item_requirements()`, item-scoped report paths, and state persistence; only advance to `待实施` after human approval.
- [ ] Re-run the targeted tests and observe PASS.

### Task 3: Route requirement-change feedback

**Files:** Modify `break_pipeline.py`; modify `tests/test_break_pipeline.py`.

- [ ] Write tests for requirement-change feedback returning to requirements analysis and implementation-only feedback avoiding that gate.
- [ ] Run targeted tests and observe failure.
- [ ] Add an explicit `需求变更:` feedback marker and route only marked code/human feedback to `待需求分析`.
- [ ] Run `python3 -m unittest tests.test_break_pipeline tests.test_break_main -v` and observe PASS.

### Task 4: Verify and commit

- [ ] Run `python3 -m unittest discover -s tests -v` and record unrelated baseline failures separately.
- [ ] Run `git diff --check`, inspect the scoped diff, and commit only item-requirement-gate files.

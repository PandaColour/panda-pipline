# Per-Item Workspace Reports Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Isolate every small requirement's requirements, development, testing, and review artifacts in its own directory.

**Architecture:** The index points at `R-xxx-name/user_requirements.md`; `BreakPipeline` derives every other report from that parent directory. Prompt files mirror the original role templates while constraining artifact writes to the current item directory.

**Tech Stack:** Python standard library and `unittest`.

## Global Constraints

- Do not modify `pipeline.py` or original `system-prompt/` behavior.
- Current-item workflow artifacts must never share a directory with another item.
- `user_requirements.md`, `develop_report.md`, and `test_report.md` use the original templates.

---

### Task 1: Derive item-local artifact paths

**Files:** Modify `break_pipeline.py`; modify `tests/test_break_pipeline.py`.

- [ ] Write a failing test where `index.md` names `R-001-login/user_requirements.md` and assert every agent prompt contains only that item's `user_requirements.md`, `develop_report.md`, `test_report.md`, `requirement_review.md`, and `code_review.md` paths.
- [ ] Run `python3 -m unittest tests.test_break_pipeline -v` and observe failure.
- [ ] Add a `RequirementItem.workspace_dir`-derived path helper; remove shared `requirements/reports/` paths.
- [ ] Re-run the test command and observe PASS.

### Task 2: Replace prompt contracts with original-template-compatible versions

**Files:** Modify every `break-system-prompt/*.md`; modify `tests/test_break_pipeline.py`.

- [ ] Write failing prompt-contract tests for memory policy, report headings, output paths, and no-cross-item writes.
- [ ] Run the targeted tests and observe failure.
- [ ] Copy the relevant role rules and complete report templates from `system-prompt/`, replacing generic paths with the supplied current-item absolute paths.
- [ ] Re-run `python3 -m unittest tests.test_break_pipeline -v` and observe PASS.

### Task 3: Verify scoped workflow behavior

- [ ] Run `python3 -m unittest tests.test_break_pipeline tests.test_break_main -v`.
- [ ] Run `python3 -m unittest discover -s tests -v`; record existing unrelated failures separately.
- [ ] Run `git diff --check`, inspect changed paths, and commit only the scoped files.

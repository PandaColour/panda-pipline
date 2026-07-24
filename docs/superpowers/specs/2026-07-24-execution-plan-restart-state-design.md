# Execution Plan Restart State Design

## Context

The break pipeline currently persists item progress in `requirements/execution_plan.json`, but the workflow status is mostly inferred from item status and in-memory state. Restart recovery works for some gates, but broad statuses such as `开发中` cannot distinguish "developer still running" from "developer finished and reviewer should resume". Pending human or review feedback is also held in memory, so it is lost when the Python process restarts.

This design makes `execution_plan.json` the single durable state source. Agents produce artifacts and structured answers; Python owns all status transitions.

## Goals

- Persist the overall demand status in `execution_plan.json`.
- Persist each small requirement's workflow status in `execution_plan.json`.
- Make restart behavior deterministic without relying on live Agent sessions.
- Archive completed demand folders as numbered `requirements-001`, `requirements-002`, etc.
- Keep current `requirements/` as the active demand workspace.

## Non-Goals

- Do not make Agents directly edit lifecycle status.
- Do not move project memory into `execution_plan.json`.
- Do not introduce watchdog logic for hung child processes.
- Do not change the business meaning of requirement, review, development, or memory artifacts.

## Execution Plan Schema

Use `schema_version: 2`.

Top-level demand state:

- `拆分中`
- `拆分评审中`
- `开发中`
- `记忆整理中`
- `已完成`
- `阻塞`

Small requirement state:

- `需求分析中`
- `需求评审中`
- `待开发`
- `开发中`
- `代码评审中`
- `待人工确认`
- `记忆整理中`
- `已完成`
- `阻塞`

Each item may also hold durable feedback:

- `pending_feedback`: `null` or an object containing `kind`, `source_status`, `message`, and `created_at`.

Artifacts remain normal files under each requirement directory. The plan may include artifact paths for observability, but files remain the source for report contents.

## State Ownership

Python is the only component allowed to update lifecycle state. It updates the plan after each successful transition:

- Before calling a stage Agent, move the item or demand into the corresponding in-progress state.
- After an approval token or human approval, advance to the next state.
- After changes requested, persist `pending_feedback` and move to the matching rework state.
- After an exception or external blocker, keep the last durable state and record failure context if available.

Agents only read state, write their assigned artifacts, and return structured decisions.

## Restart Behavior

On startup, the pipeline reads the active `requirements/execution_plan.json` and resumes by state:

- Demand `拆分中`: resume or rerun requirement breakdown for the active `requirements/`.
- Demand `拆分评审中`: resume breakdown review.
- Demand `开发中`: select the next runnable item.
- Demand `记忆整理中`: resume final demand-level memory curation.
- Demand `已完成`: archive if needed, then wait for the next demand.

For items:

- `需求分析中`: resume requirement analysis.
- `需求评审中`: run requirement review, not analysis.
- `待开发`: start development.
- `开发中`: resume development.
- `代码评审中`: run code review, not development.
- `待人工确认`: resume the human gate.
- `记忆整理中`: resume item memory curation.
- `已完成`: never run again.

If an item has `pending_feedback`, Python passes it into the next relevant Agent call and clears it only after the Agent has accepted the work and the state advances.

## Demand Archiving

The active demand always uses `requirements/`.

When all items are `已完成` and demand-level memory curation is complete:

1. Set demand status to `已完成`.
2. Find the next archive directory name by scanning `requirements-001`, `requirements-002`, etc.
3. Rename `requirements/` to that archive directory.
4. Create a fresh `requirements/` only when a new demand starts.

Archive directory names use the correct spelling: `requirements-001`, not `reqirments` or `reqirements`.

## Compatibility

Existing schema v1 plans should be normalized into schema v2 when possible:

- Preserve item identity and item status.
- Map old statuses to the closest v2 status.
- Derive demand status from item statuses when absent.
- Preserve source hash validation for `requirements/index.md`.

## Testing

Add focused tests for:

- Schema v2 validation and status persistence.
- Restart at `代码评审中` runs reviewer without rerunning developer.
- Restart at `待人工确认` resumes only the human gate.
- Restart at `记忆整理中` resumes memory curation.
- Pending feedback survives a new `BreakPipeline` instance.
- Completed demand archives `requirements/` as the next numbered directory.
- Schema v1 execution plans are migrated or normalized without losing completed item statuses.

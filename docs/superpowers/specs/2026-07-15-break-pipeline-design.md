# Break Pipeline Design

## Goal

Provide an independent workflow that turns one large user request into ordered,
small requirements that are individually implementable and verifiable, obtains
review and human approval for the breakdown, then implements each requirement
through its own development, testing, code-review, and human-approval cycle.

## Scope and boundaries

- Add a separate entry point, `break_main.py`, and orchestrator,
  `break_pipeline.py`.
- Add all new prompts under `break-system-prompt/`.
- Keep the existing `main.py`, `pipeline.py`, and `system-prompt/` workflow
  behavior unchanged.
- Preserve per-item human approval after code review. A rejection or requested
  change may affect only the current item; later items must not start.
- This version does not support changing the execution order after the
  breakdown has been approved, nor automatically re-running completed items.

## Architecture

`break_main.py` prepares repositories using the same clone/update and working
directory resolution conventions as `main.py`. It creates `BreakPipeline` with
the resolved work directory and calls `run()`.

`BreakPipeline` owns two phases:

1. **Breakdown:** prompt for the large requirement; ask a breakdown agent to
   create `requirements/index.md` and individual requirement files; loop with
   a breakdown-review agent until its explicit approval; then request one
   human approval for the whole breakdown.
2. **Execution:** read the approved index, validate its dependency graph, and
   process requirements in order. Each item runs developer, tester, and code
   reviewer agents. After reviewer approval, a human gate approves or returns
   feedback for only that item.

All agents run in the target repository root and receive absolute paths for
every required input and report file.

## Files and responsibilities

| Path | Responsibility |
| --- | --- |
| `break_main.py` | Independent executable entry point and repository setup. |
| `break_pipeline.py` | Breakdown, review, status, dependency, and item-execution orchestration. |
| `break-system-prompt/requirement_breaker.md` | Produces small, ordered, verifiable requirements and the index. |
| `break-system-prompt/requirement_break_reviewer.md` | Rejects incomplete, overlapping, non-verifiable, or incorrectly ordered decompositions. |
| `break-system-prompt/item_developer.md` | Implements only the currently selected requirement and writes its development report. |
| `break-system-prompt/item_tester.md` | Tests only the currently selected requirement and affected regression paths. |
| `break-system-prompt/item_code_reviewer.md` | Reviews only the current item's requirement, implementation, and tests. |
| `tests/test_break_pipeline.py` | Unit tests for the new workflow. |
| `tests/test_break_main.py` | Unit tests for entry-point repository setup behavior. |

## Breakdown artifacts

The target repository receives this structure:

```text
requirements/
├── index.md
├── 001-<short-name>.md
├── 002-<short-name>.md
└── reports/
    ├── R-001-develop.md
    ├── R-001-test.md
    └── R-001-review.md
```

`requirements/index.md` is the only execution ledger. It contains an ordered
Markdown table with these columns:

| Order | ID | Name | Status | Depends on | File | Acceptance summary |
| --- | --- | --- | --- | --- | --- | --- |

Allowed statuses are exactly: `待审核`, `待实施`, `开发中`, `待人工确认`,
`已完成`, `返工中`, and `阻塞`.

Each `requirements/<order>-<short-name>.md` contains:

1. ID, name, priority, and status.
2. Goal and user value.
3. In-scope and out-of-scope behavior.
4. Dependencies, affected areas, and why this execution order is required.
5. Functional behavior and error/boundary cases.
6. Observable, testable acceptance criteria.
7. Implementation constraints, risks, and unresolved questions.
8. Absolute or index-relative paths for that item's reports.

An item is valid only when it can pass one independent development, test,
review, and human-approval cycle. The breakdown agent must split any item that
requires separately releasable or separately testable behavior.

## Control flow

### Breakdown

1. Prompt the user for the large requirement.
2. The breakdown agent inspects project facts and writes the complete
   `requirements/` structure.
3. The breakdown-review agent checks coverage, granularity, absence of
   overlap, dependency order, acceptance criteria, and unsupported assumptions.
4. Rejected feedback returns only to the breakdown agent. The review repeats
   until its response contains `拆分方案通过`.
5. The human gate reviews `requirements/index.md` and the requirement folder.
   Feedback returns to the breakdown agent; an empty response approves the
   breakdown and starts execution.

### Per-item execution

1. Read and validate the index before selecting an item: unique IDs and file
   paths, existing files, known dependencies, no cyclic dependencies, and no
   item ordered before an unfinished dependency.
2. Select the first `待实施` or `返工中` item whose dependencies are all
   `已完成`; otherwise mark unresolved eligible items `阻塞` and stop with a
   useful diagnostic.
3. Set the selected item to `开发中` in `index.md`.
4. Ask developer, tester, and reviewer agents to work only on the selected
   requirement and its item-scoped report paths.
5. If code review does not contain `任务完成`, send that feedback only to the
   current developer and repeat testing and review for that item.
6. On code-review approval, set the current status to `待人工确认` and invoke
   the human gate.
7. Human approval sets the item to `已完成`; feedback sets it to `返工中` and
   returns only to the current developer. Human exit terminates without
   changing later items.

Every status transition is written to `index.md` before the next agent call,
so a later invocation can continue from remaining unfinished work.

## Prompt contracts

- `requirement_breaker.md` must create and update only the `requirements/`
  breakdown artifacts. It must use verified repository facts and identify
  uncertain information rather than inventing it.
- `requirement_break_reviewer.md` must include `拆分方案通过` only when every
  item meets the granularity, dependency, and verifiability rules; failed
  responses must contain actionable feedback and must not include that token.
- The three item prompts must say that no other requirement may be implemented,
  tested, or marked complete. Their reports use the current item ID in their
  filenames.
- Empty or missing reviewer responses are errors, never implicit approval.

## Error handling and recovery

- A missing or malformed index, unknown status, invalid table column, duplicate
  ID, missing requirement file, unknown dependency, cyclic dependency, or
  dependency-order violation halts before implementation with an explicit
  error.
- A breakdown reviewer failure or empty response halts with an error rather
  than allowing human approval of an unreviewed plan.
- Existing completed items remain untouched on restart. Items in `开发中` or
  `待人工确认` are made resumable by retaining their status and report paths;
  the operator can send feedback through the normal current-item cycle.

## Verification

Automated tests will cover prompt file lookup, artifact paths, review feedback
loops, human feedback loops, current-item-only prompts, index status updates,
dependency ordering and validation, blocked states, review-token enforcement,
and restart selection of the next unfinished item. Existing tests must keep
passing unchanged.

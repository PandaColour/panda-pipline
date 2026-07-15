# Item Requirement Gates Design

Each approved breakdown item must complete its own requirements workflow
before development:

```text
待需求分析 → 需求分析 → 需求评审 → 需求人工确认 → 待实施
→ 开发 → 测试验收 → 代码审查 → 代码人工确认 → 已完成
```

`item_requirements_analyst.md` enriches only the current item file with
scope, affected areas, boundary/error cases, acceptance criteria, dependencies,
and risks. `item_requirements_reviewer.md` evaluates that document and must
return `同意方案` only when it is implementable and verifiable. Their reports
are written to `requirements/reports/R-xxx-requirements-analysis.md` and
`R-xxx-requirements-review.md`.

The index adds the statuses `待需求分析`, `待需求评审`, `需求返工中`, and
`待需求人工确认`. Breakdown items begin as `待需求分析`; only requirement
human approval moves an item to `待实施`.

On a requirements-review or requirements-human rejection, only the current
item returns to the item requirements analyst and later items remain untouched.
If a code-review or code-human feedback explicitly says the requirement must
change, the current item returns to `待需求分析`; it must complete the two
requirements gates again before fresh development. Feedback that concerns only
implementation keeps the current development/test/code-review loop and does
not repeat requirements analysis.

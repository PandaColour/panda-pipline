# Per-Item Workspace and Report Design

Every split requirement owns one self-contained workspace beneath
`requirements/`:

```text
requirements/
├── index.md
├── R-001-login/
│   ├── user_requirements.md
│   ├── requirement_review.md
│   ├── develop_report.md
│   ├── test_report.md
│   ├── code_review.md
│   └── bug_report.md          # only when testing finds a defect
└── R-002-profile/
    └── ...
```

The index `文件` column stores the relative path to each item's
`user_requirements.md`, for example `R-001-login/user_requirements.md`.
There is no shared `requirements/reports/` directory.

All item agents receive absolute paths for the current item's directory and
its reports. They may inspect repository code and optional shared project
facts, but may create or update workflow artifacts only in the specified item
directory; they must not read, modify, or mark another item complete.

Prompt contracts mirror the existing `system-prompt/` rules:

- The item requirements analyst writes `user_requirements.md` with the full
  requirements template: overview, scope/boundaries, functional requirements,
  impact analysis, dependency order, acceptance criteria, and risks.
- The item requirements reviewer reads that file, writes
  `requirement_review.md`, and returns `同意方案` only when it is actionable,
  verifiable, and grounded in repository facts.
- The item developer reads `user_requirements.md`, writes
  `develop_report.md` with overview, changes, verification, implementation
  status, and handoff risks; it does not write tests.
- The item validation-review agent reads the requirement and development report,
  writes `test_report.md` with overview, cases, execution results, remaining
  issues, and writes `bug_report.md` only for observed defects.
- The item code reviewer reads the three primary reports and writes
  `code_review.md`; its only passing token is `任务完成`.

Each prompt retains the original memory policy: project memory is optional
input and must never be changed unless explicitly requested. All assertions
must distinguish verified facts, assumptions, and unresolved questions.

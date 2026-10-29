---
name: sql-guard-change
description: Procedure for changing the SQL validator (allowed functions, types, forbidden statements, repairable reasons) or the EXPLAIN cost guard and its thresholds. Use whenever a change touches src/finql/text_to_sql/validator.py, cost_guard.py or the sql_max_* settings.
argument-hint: "[function, rule or threshold to change]"
---

# Validator or cost guard change: $ARGUMENTS

The validator decides what LLM-written SQL may run. It is an **allowlist**: anything not listed
is rejected. The tempting mistake is to add a function or loosen a rule because one eval question
failed. That makes the eval greener and the system less safe. The database layers (read-only
role, RLS) would still hold, but this layer exists so that they are never the only defence.

## 1. Justify before changing

Write down, in the PR description:

- **Why is this needed?** A real question that users ask, not a single eval failure. If an eval
  question failed, first check whether the golden SQL or the prompt is the problem.
- **For a new allowed function or type:** can it read outside `analytics` (catalog, files,
  settings), cause side effects, sleep or loop (`pg_sleep`, `generate_series` on huge ranges),
  or reveal server information? If yes to any, it does not go in.
- **For a threshold change** (`sql_max_plan_rows`, `sql_max_cost`, `sql_max_limit` in
  `core/config.py`): the measurement behind it. ADR-006: the current limits were measured on the
  `large` scale (legitimate queries ≤ ~8 M estimated rows, bad joins ≥ ~70 M). RLS makes the
  estimated *cost* misleading, which is why the row estimate is the main measure.

## 2. Change, where the rule lives

In `src/finql/text_to_sql/validator.py`:

| Constant | Meaning |
|---|---|
| `FORBIDDEN_NODES` | Statement types never allowed anywhere (writes, DDL, …) |
| `ALLOWED_FUNCTIONS` / `ALLOWED_FUNCTION_NAMES` | The function allowlist (sqlglot node types / names) |
| `DANGEROUS_FUNCTION_PREFIXES` | Names rejected as forbidden intent, not as a slip |
| `ALLOWED_TYPES` | Types allowed in casts |
| `REPAIRABLE` | Reasons that give the model a second try |

**Forbidden intent is never repairable.** Only slips (an unknown but harmless function, a
disallowed cast) may go to `REPAIRABLE`. A write or a catalog read gets no second chance.

The SQL that runs is regenerated from the AST, not the model's text. Keep it that way.

## 3. Tests: both directions

In `tests/unit/text_to_sql/test_validator.py`:

- Every newly **allowed** construct: a case in `LEGITIMATE`.
- Every newly **blocked** construct, and every way you can think of to misuse a newly allowed one:
  an entry in `MALICIOUS` with the expected `RejectReason`.
- Then prove the tests bite: revert the change in `validator.py` and confirm that the new tests
  fail, then restore it.

For a threshold change: a test in `tests/unit/text_to_sql/test_prompt_and_guard.py` or the
integration tests at the new boundary.

## 4. Verify

1. `uv run poe check`: read the full output.
2. `uv run poe eval-oracle` (free): must stay 100%. The golden SQL must still pass the validator.
3. The adversarial set (`eval/datasets/adversarial.yaml`, 20 questions) needs the real model:
   `uv run finql eval run --dataset adversarial` **costs money; ask before running it.** It must
   stay 20/20.

## 5. Report

The justification, the diff in one sentence per constant, the new test cases, the result of the
"revert and see it fail" check, and the verification output. If you changed a threshold, update
ADR-006 in `docs/02-technologiai-dontesek.md` with the new measurement.

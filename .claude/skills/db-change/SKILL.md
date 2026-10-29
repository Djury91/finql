---
name: db-change
description: Procedure for changing the FinQL database - bank schema, analytics views, roles, RLS policies, grants, comments, triggers or app-schema tables and their Alembic migrations. Use whenever a change touches db/ or migrations/.
argument-hint: "[what should change]"
---

# Database change: $ARGUMENTS

FinQL's database is hybrid (ADR-002). Mistakes here are silent: the app still starts, the tests
for the old behaviour still pass, but a branch manager may see another branch's rows, or the
model may lose a column it needs. Follow the steps in order and report each one.

## 1. Classify the change

| What changes | Where it goes |
|---|---|
| `bank` tables, types, indexes, grants | DB-first: a new SQL file under `db/bank/` |
| `analytics` views, comments, ownership | DB-first: `db/analytics/` |
| Roles | `db/roles/001_roles.sql` (run by `finql db bootstrap`, not by Alembic) |
| RLS policies, session context | DB-first: `db/security/` |
| Triggers, functions, append-only rules in `app` | DB-first: `db/app/` |
| Plain `app` tables and columns | Code-first: ORM model in `src/finql/<domain>/models.py`, then `alembic revision --autogenerate` |

**SQL files that an existing migration already runs are not edited.** Databases that were migrated
earlier would never see the change (Alembic does not run a migration twice), so a fresh database
and an upgraded one would drift apart. Add a new numbered file and a new migration that calls
`run_sql_file("<dir>/<file>.sql")`, the same way as `migrations/versions/0010_log_hash_chain.py`.

## 2. Write it, with the known traps in mind

- **RLS.** Policies target `finql_analytics`, the owner of the analytics views. A new branch-bound
  table needs `ENABLE ROW LEVEL SECURITY` and a `branch_scope` policy in the existing pattern:
  `USING ((SELECT app_ctx.all_branches()) OR branch_id = (SELECT app_ctx.branch_id()))`.
  Keep the `(SELECT …)` wrapper: it makes the function run once (InitPlan); without it the row
  estimate was ~200x off and the plan turned into nested loops (see `db/security/010_rls.sql`).
- **No `security_barrier` on the analytics views.** RLS already filters first, and the barrier
  stopped enum filters from being pushed down (non-LEAKPROOF `=`).
- **A new or replaced analytics view** must end up owned by `finql_analytics` with `SELECT` for
  `finql_llm_reader`: run `analytics/099_ownership_grants.sql` again as the last step of the
  migration (it loops over every view). Write the `COMMENT ON` statements before that, because
  after the ownership change the migration role can no longer comment. To change an existing
  view, the migration role can `SET ROLE finql_analytics` (granted `WITH INHERIT FALSE, SET TRUE`
  in `db/roles/001_roles.sql`).
- **Comments are part of the prompt.** `schema_context.py` reads `COMMENT ON VIEW/COLUMN` and
  shows it to the model. A view or column without a clear Hungarian comment is a column the model
  will misuse. Put them in `db/analytics/090_comments.sql` style, in the new file.
- **No PII in `analytics`.** Names, tax ids, phone numbers and addresses stay in `bank`; IBANs are
  masked. `tests/integration/test_security.py` checks this.
- **Partitions on `timestamptz`** are bounded with `make_timestamptz(..., 'Europe/Budapest')`;
  plain date literals are read in the session time zone.
- **Autogenerate** knows no grants, triggers, functions, RLS or enum drops. Review the generated
  file, and check that `downgrade()` really undoes everything (in phase 2 the generated downgrade
  would have left an enum type behind; review caught it).

## 3. Tests (against a real Postgres)

Add to `tests/integration/`, following the existing tests:

- A new branch-bound view: add it to `BRANCH_BOUND` in `test_security.py` so the existing
  parametrized tests cover it (empty without context, exactly the own branch, all rows in
  `all` scope).
- A new column: if it could hold personal data, extend `test_analytics_exposes_no_pii_columns`.
- A new grant or role: a test that the LLM role still cannot write and still sees only `analytics`.

## 4. Verify

1. `uv run poe check`: read the full output.
2. Upgrade path: on an existing local database, `uv run poe db-migrate`, then check the result
   with `uv run alembic current` (a filtered log has hidden a failed migration before).
3. Downgrade once and upgrade again if the migration has a non-trivial `downgrade()`.
4. If an analytics view changed: `uv run poe eval-oracle` (free) must still be 100%, otherwise
   a golden SQL in `eval/datasets/golden.yaml` depends on what you changed.

## 5. Report

Which files, which migration number, which tests were added, the output of steps 4.1–4.4, and
anything you could not verify. Update `docs/04-adatbazis.md` if the data model changed.

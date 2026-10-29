# FinQL: guide for coding agents

FinQL turns Hungarian questions into validated, read-only SQL on a sample bank database, answers
from policy documents with citations, and logs every step. Design docs are in `docs/` (Hungarian);
the decisions are the ADRs in `docs/02-technologiai-dontesek.md`. Read the relevant ADR before
changing something it covers.

## The rule behind everything

**The model proposes, the code and the database decide.** Never move a guarantee from code or SQL
into a prompt. Security lives in layers, strongest at the bottom: AST validator (sqlglot) → cost
guard (EXPLAIN) → read-only role `finql_llm_reader` → Row-Level Security. A change may not weaken a
lower layer because an upper one "already handles it".

## How to work here

1. **Plan first** for anything beyond a one-file fix: which files, which tests, which ADR applies.
2. **One branch and one PR per change** (`feat/…`, `fix/…`, `docs/…`); never commit to `main`
   directly. PRs are squash-merged once CI is green. Commit messages are Hungarian, conventional style with a scope:
   `feat(rag): …`, `fix(auth): …`, `docs: …`.
3. **Done means `uv run poe check` is green** (ruff, format check, mypy, all tests incl. Docker
   integration tests). Read the full output; do not filter it with `grep`, which has hidden a
   failed migration before.
4. **A test proves every guarantee.** Database guarantees (RLS, roles, append-only and
   hash-chained logs) are tested against a real Postgres, never mocked.

## Commands

| Command | Notes |
|---|---|
| `uv run poe check` | Same as CI. Needs Docker (testcontainers starts `pgvector/pgvector:pg18`). |
| `uv run poe test-unit` | Fast, no Docker. |
| `uv run poe db-setup` | Local DB from scratch: Docker → roles → migrations → seed (~1 min). |
| `uv run poe eval-oracle` | Free self-check of the eval harness; must be 100%. |
| `uv run poe eval-retrieval` | Free document-search metrics (no LLM). |
| `uv run poe eval`, `eval-agent`, `test-llm` | **Call the real Anthropic API and cost money. Ask first.** |

On Windows, testcontainers runs with Ryuk disabled (`tests/integration/conftest.py`), and the CLI
forces UTF-8 output.

## Code conventions

- Python 3.12, FastAPI, SQLAlchemy 2.0 async, Pydantic v2. Full type hints; mypy is strict.
- **Domain modules** (`src/finql/<domain>/` with `router`, `service`, `models`, `schemas`);
  `api → service → db/llm`. Modules may call each other's service, never each other's router.
  `core/` depends on nothing. See `docs/06-mappaszerkezet.md`.
- **Language:** code, comments and docstrings in English; everything a user sees (API errors, CLI
  help, UI, prompts) in Hungarian.
- **Prompts are versioned files** in `src/finql/llm/prompts/` (`text_to_sql.v1.md`). Change a
  prompt by adding a new version, not by editing the old one; eval runs record the version.
- **Keyless mode stays working.** Every LLM feature has a fake implementation (`fake_client.py`,
  `fake_chat.py`, demo mode); tests and CI never need an API key.
- No bank data in logs or traces; the `query_log` id links them.

## Database: hybrid, read before touching

- **DB-first** (`db/`): bank schema, analytics views, roles, RLS, grants, comments, triggers. Hand
  written SQL, run from Alembic via `run_sql_file()`.
- **Code-first** (`migrations/`, autogenerate): only the `app` schema tables. Autogenerate knows no
  grants, triggers, functions or RLS; review every generated migration.
- For any schema, view, role or RLS change use the **`db-change`** skill.

## Skills in this repo

| Skill | Use it when |
|---|---|
| `/db-change` | Changing `db/`, a migration, a view, a role, an RLS policy or a grant |
| `/sql-guard-change` | Changing the SQL validator's allowlists or the cost guard |
| `/eval-check` | Changing a prompt, the model, few-shot or retrieval, and you need to know if it got better |

## Never

- Commit anything under `private/` (personal notes; a pre-commit hook blocks it) or any `.env`.
- Read or print `.env`; it holds real keys.
- Loosen the validator, a test or a threshold to make an eval question pass.
- Run paid commands (see above) without asking.

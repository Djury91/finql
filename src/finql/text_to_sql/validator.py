"""Validation of LLM-generated SQL on the syntax tree (sqlglot), before it reaches the database.

The LLM's output is untrusted input. The rules (docs/05-text-to-sql-biztonsag.md):

1. Exactly one statement.
2. The root is a SELECT or a set operation (UNION/INTERSECT/EXCEPT), with optional CTEs.
   Nowhere in the tree: data modification (also not in a CTE), DDL, commands, SELECT INTO,
   FOR UPDATE/SHARE, bind parameters.
3. Every table is an allowed analytics view or one of the query's own CTEs.
4. Functions and cast types from an ALLOWLIST. A denylist always misses something, and one
   `set_config('app.scope', 'all', true)` would widen the row-level security context.
5. LIMIT: added if missing, lowered if above the maximum.
6. The SQL that runs is regenerated from the tree (no comments), not the model's raw text.

The database enforces read-only access and row-level security independently (layers 4-5), so a
gap here alone does not mean a write or a leak.
"""

import enum
from dataclasses import dataclass

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError, TokenError

from finql.core.errors import AppError

DIALECT = "postgres"
SCHEMA = "analytics"
MAX_SQL_LENGTH = 20_000


class RejectReason(enum.StrEnum):
    EMPTY = "empty"
    TOO_LONG = "too_long"
    PARSE_ERROR = "parse_error"
    MULTIPLE_STATEMENTS = "multiple_statements"
    NOT_SELECT = "not_select"
    FORBIDDEN_STATEMENT = "forbidden_statement"
    SELECT_INTO = "select_into"
    LOCKING_CLAUSE = "locking_clause"
    PARAMETER = "parameter"
    FORBIDDEN_TABLE = "forbidden_table"
    UNKNOWN_TABLE = "unknown_table"
    FORBIDDEN_FUNCTION = "forbidden_function"
    FUNCTION_NOT_ALLOWED = "function_not_allowed"
    CAST_NOT_ALLOWED = "cast_not_allowed"


# A rejection the model may get a second chance at (a typo, a view or function it made up).
# Never for a forbidden intent: writing, the system catalog, the session context.
REPAIRABLE = frozenset(
    {
        RejectReason.PARSE_ERROR,
        RejectReason.UNKNOWN_TABLE,
        RejectReason.FUNCTION_NOT_ALLOWED,
        RejectReason.CAST_NOT_ALLOWED,
    }
)


class SqlRejectedError(AppError):
    status_code = 422
    code = "sql_rejected"
    message = "A generált SQL nem felel meg a biztonsági szabályoknak."

    def __init__(self, reason: RejectReason, message: str) -> None:
        super().__init__(message)
        self.reason = reason

    @property
    def repairable(self) -> bool:
        return self.reason in REPAIRABLE


@dataclass(frozen=True)
class ValidatedQuery:
    sql: str  # regenerated from the syntax tree, with the enforced LIMIT
    views: frozenset[str]  # the analytics views it reads
    limit: int


# Statements and clauses that never belong in a read-only analytical query, at any depth
# (`WITH d AS (DELETE … RETURNING *) SELECT …` has a SELECT root).
FORBIDDEN_NODES: tuple[type[exp.Expr], ...] = (
    exp.DML,  # INSERT, UPDATE, DELETE, MERGE, COPY
    exp.DDL,  # CREATE, …
    exp.Drop,
    exp.Alter,
    exp.TruncateTable,
    exp.Command,  # what sqlglot does not parse: DO, CALL, EXPLAIN, SHOW, VACUUM, PREPARE, …
    exp.Set,
    exp.Transaction,
    exp.Commit,
    exp.Rollback,
    exp.Grant,
    exp.Revoke,
    exp.Analyze,
    exp.Use,
    exp.Pragma,
)

# sqlglot parses the functions it knows into typed nodes; this is the allowed set of those.
ALLOWED_FUNCTIONS: tuple[type[exp.Expr], ...] = (
    # syntax that sqlglot models as a function
    exp.And,
    exp.Or,
    exp.Case,
    exp.If,
    exp.Cast,
    exp.Coalesce,
    exp.Nullif,
    exp.Greatest,
    exp.Least,
    exp.Extract,
    exp.Exists,
    exp.Array,
    # aggregates
    exp.Count,
    exp.Sum,
    exp.Avg,
    exp.Min,
    exp.Max,
    exp.Stddev,
    exp.StddevPop,
    exp.StddevSamp,
    exp.Variance,
    exp.VariancePop,
    exp.Corr,
    exp.CovarPop,
    exp.CovarSamp,
    exp.PercentileCont,
    exp.PercentileDisc,
    exp.Mode,
    exp.ArrayAgg,
    exp.GroupConcat,  # string_agg
    exp.LogicalAnd,  # bool_and
    exp.LogicalOr,  # bool_or
    # window functions
    exp.RowNumber,
    exp.Rank,
    exp.DenseRank,
    exp.PercentRank,
    exp.CumeDist,
    exp.Ntile,
    exp.Lag,
    exp.Lead,
    exp.FirstValue,
    exp.LastValue,
    exp.NthValue,
    # numbers
    exp.Abs,
    exp.Round,
    exp.Floor,
    exp.Ceil,
    exp.Trunc,
    exp.Sign,
    exp.Sqrt,
    exp.Pow,
    exp.Exp,
    exp.Ln,
    exp.Log,
    exp.WidthBucket,
    # dates and times
    exp.CurrentDate,
    exp.CurrentTimestamp,
    exp.Localtimestamp,
    exp.TimestampTrunc,  # date_trunc
    exp.DateTrunc,
    exp.DateBin,
    exp.MakeInterval,
    exp.JustifyInterval,
    exp.TimeToStr,  # to_char
    exp.StrToDate,  # to_date
    exp.StrToTime,  # to_timestamp(text, format)
    exp.UnixToTime,  # to_timestamp(number)
    # text
    exp.Lower,
    exp.Upper,
    exp.Initcap,
    exp.Length,
    exp.Substring,
    exp.Trim,
    exp.Pad,
    exp.Left,
    exp.Right,
    exp.Concat,
    exp.ConcatWs,
    exp.Replace,
    exp.SplitPart,
    exp.StrPosition,
    exp.RegexpLike,
    exp.RegexpReplace,
    # sets and arrays
    exp.ArraySize,
    exp.Explode,  # unnest in SELECT
    exp.Unnest,  # unnest in FROM
    exp.ExplodingGenerateSeries,  # generate_series in FROM
    exp.GenerateSeries,
)

# Functions sqlglot does not know arrive as Anonymous: allowed by name.
ALLOWED_FUNCTION_NAMES = frozenset(
    {
        "age",
        "array_to_string",
        "cardinality",
        "date_part",
        "every",
        "isfinite",
        "justify_days",
        "justify_hours",
        "make_date",
        "make_time",
        "make_timestamp",
        "make_timestamptz",
        "num_nonnulls",
        "num_nulls",
        "string_to_array",
        "timezone",  # AT TIME ZONE
        "to_number",
    }
)

# Only to classify a rejection as an attack rather than a slip (no second chance). The
# allowlists above reject these anyway, with or without this list.
DANGEROUS_FUNCTION_PREFIXES = (
    "set_config",
    "current_setting",
    "pg_",
    "lo_",
    "dblink",
    "query_to_xml",
    "table_to_xml",
    "cursor_to_xml",
    "database_to_xml",
    "schema_to_xml",
    "has_",
    "current_",  # current_user, current_schema, current_version, … (not current_date)
    "session_user",
    "version",
    "inet_",
    "txid_",
    "nextval",
    "setval",
    "currval",
)

ALLOWED_TYPES = frozenset(
    {
        exp.DataType.Type.BIGINT,
        exp.DataType.Type.BOOLEAN,
        exp.DataType.Type.CHAR,
        exp.DataType.Type.DATE,
        exp.DataType.Type.DECIMAL,
        exp.DataType.Type.DOUBLE,
        exp.DataType.Type.FLOAT,
        exp.DataType.Type.INT,
        exp.DataType.Type.INTERVAL,
        exp.DataType.Type.SMALLINT,
        exp.DataType.Type.TEXT,
        exp.DataType.Type.TIME,
        exp.DataType.Type.TIMESTAMP,
        exp.DataType.Type.TIMESTAMPTZ,
        exp.DataType.Type.VARCHAR,
        exp.DataType.Type.ARRAY,  # its element type is checked as its own DataType node
    }
)


def validate_sql(
    sql: str, *, allowed_views: frozenset[str], default_limit: int, max_limit: int
) -> ValidatedQuery:
    """Return the query to run, or raise SqlRejectedError with the reason."""
    if not sql.strip():
        raise SqlRejectedError(RejectReason.EMPTY, "Az SQL üres.")
    if len(sql) > MAX_SQL_LENGTH:
        raise SqlRejectedError(RejectReason.TOO_LONG, "Az SQL túl hosszú.")

    statement = _parse_single(sql)
    _check_root(statement)
    _check_nodes(statement)
    views = _check_tables(statement, allowed_views)
    _check_functions(statement)
    _check_types(statement)
    limit = _enforce_limit(statement, default_limit=default_limit, max_limit=max_limit)
    return ValidatedQuery(
        sql=statement.sql(dialect=DIALECT, comments=False, pretty=True),
        views=views,
        limit=limit,
    )


def _parse_single(sql: str) -> exp.Expr:
    try:
        statements = [s for s in sqlglot.parse(sql, dialect=DIALECT) if s is not None]
    except (ParseError, TokenError) as exc:
        raise SqlRejectedError(
            RejectReason.PARSE_ERROR, f"Az SQL nem értelmezhető: {_first_line(exc)}"
        ) from exc
    if len(statements) != 1:
        raise SqlRejectedError(
            RejectReason.MULTIPLE_STATEMENTS, "Pontosan egy SQL-utasítás engedélyezett."
        )
    return statements[0]


def _check_root(statement: exp.Expr) -> None:
    if isinstance(statement, FORBIDDEN_NODES):
        raise SqlRejectedError(
            RejectReason.FORBIDDEN_STATEMENT,
            f"Csak lekérdezés (SELECT) engedélyezett, ez pedig: {_statement_name(statement)}.",
        )
    if not isinstance(statement, exp.Select | exp.SetOperation):
        raise SqlRejectedError(RejectReason.NOT_SELECT, "Csak lekérdezés (SELECT) engedélyezett.")


def _check_nodes(statement: exp.Expr) -> None:
    for node in statement.walk():
        if isinstance(node, FORBIDDEN_NODES):
            raise SqlRejectedError(
                RejectReason.FORBIDDEN_STATEMENT,
                f"Adatmódosító vagy adminisztratív művelet nem engedélyezett: "
                f"{_statement_name(node)}.",
            )
        if isinstance(node, exp.Into):
            raise SqlRejectedError(
                RejectReason.SELECT_INTO, "A SELECT … INTO nem engedélyezett (táblát hozna létre)."
            )
        if isinstance(node, exp.Lock):
            raise SqlRejectedError(
                RejectReason.LOCKING_CLAUSE, "A FOR UPDATE/SHARE zárolás nem engedélyezett."
            )
        if isinstance(node, exp.Placeholder | exp.Parameter):
            raise SqlRejectedError(
                RejectReason.PARAMETER,
                "Paraméter nem lehet az SQL-ben, minden értéket konkrétan írj ki.",
            )


def _check_tables(statement: exp.Expr, allowed_views: frozenset[str]) -> frozenset[str]:
    cte_names = {cte.alias_or_name.lower() for cte in statement.find_all(exp.CTE)}
    views: set[str] = set()
    for table in statement.find_all(exp.Table):
        if isinstance(table.this, exp.Func):
            continue  # a table function such as generate_series(): checked with the functions
        if not isinstance(table.this, exp.Identifier):
            raise SqlRejectedError(
                RejectReason.FORBIDDEN_TABLE, "Nem engedélyezett táblahivatkozás."
            )
        name = table.name if table.this.quoted else table.name.lower()
        schema = table.db.lower()
        shown = f"{table.db}.{table.name}" if table.db else table.name
        if table.catalog or (schema and schema != SCHEMA):
            raise SqlRejectedError(
                RejectReason.FORBIDDEN_TABLE,
                f"Csak az {SCHEMA} séma nézetei kérdezhetők le, ez nem: {shown}.",
            )
        if not schema and name in cte_names:
            continue
        if name not in allowed_views:
            raise SqlRejectedError(
                # pg_*: the system catalog (search_path resolves it), probing, not a typo
                RejectReason.FORBIDDEN_TABLE
                if name.startswith("pg_")
                else RejectReason.UNKNOWN_TABLE,
                f"Ismeretlen vagy nem engedélyezett nézet: {shown}. "
                f"Használható nézetek: {', '.join(sorted(allowed_views))}.",
            )
        views.add(name)
    return frozenset(views)


def _check_functions(statement: exp.Expr) -> None:
    for node in statement.walk():
        if isinstance(node, exp.Dot) and isinstance(node.expression, exp.Func):
            # pg_catalog.set_config(…): no schema-qualified function calls at all
            raise SqlRejectedError(
                RejectReason.FORBIDDEN_FUNCTION,
                f"Sémanévvel minősített függvényhívás nem engedélyezett: {node.sql(DIALECT)}.",
            )
        if isinstance(node, exp.Anonymous):
            name = node.name.lower()
            if name not in ALLOWED_FUNCTION_NAMES:
                raise _function_rejected(name)
        elif isinstance(node, exp.Func) and not isinstance(node, ALLOWED_FUNCTIONS):
            raise _function_rejected(node.sql_name().lower())


def _function_rejected(name: str) -> SqlRejectedError:
    if name.startswith(DANGEROUS_FUNCTION_PREFIXES):
        return SqlRejectedError(RejectReason.FORBIDDEN_FUNCTION, f"Tiltott függvény: {name}().")
    return SqlRejectedError(
        RejectReason.FUNCTION_NOT_ALLOWED,
        f"Ez a függvény nincs az engedélyezettek között: {name}(). Oldd meg nélküle.",
    )


def _check_types(statement: exp.Expr) -> None:
    for node in statement.find_all(exp.DataType):
        if node.this not in ALLOWED_TYPES:
            raise SqlRejectedError(
                RejectReason.CAST_NOT_ALLOWED,
                f"Nem engedélyezett típus: {node.sql(DIALECT)}. "
                "Használható: szám, szöveg, dátum, időpont, intervallum, logikai.",
            )


def _enforce_limit(statement: exp.Expr, *, default_limit: int, max_limit: int) -> int:
    """No LIMIT: the default. LIMIT ALL or an expression: the maximum. Above it: the maximum."""
    current = statement.args.get("limit")
    if current is None:
        limit = default_limit
    else:
        value = current.args.get("count") if isinstance(current, exp.Fetch) else current.expression
        requested = _int_literal(value)
        limit = max_limit if requested is None else min(requested, max_limit)
    statement.set("limit", exp.Limit(expression=exp.Literal.number(limit)))
    return limit


def _int_literal(node: exp.Expr | None) -> int | None:
    if isinstance(node, exp.Literal) and not node.is_string:
        try:
            return max(int(node.this), 0)
        except ValueError:
            return None
    return None


def _statement_name(node: exp.Expr) -> str:
    if isinstance(node, exp.Command):
        return str(node.this).upper()
    return node.key.upper()


def _first_line(exc: Exception) -> str:
    return str(exc).splitlines()[0][:200]

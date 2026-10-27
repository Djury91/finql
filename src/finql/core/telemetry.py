"""OpenTelemetry tracing (phase 8, ADR-014): one trace per request, from the API through the
model calls and the tools to the database.

Off unless FINQL_OTEL_ENDPOINT is set: the tracer is then the API's no-op one, and nothing is
patched. On, the spans go over OTLP/HTTP to a collector (Jaeger locally, see docker-compose.yml).

What a span may carry: model names, token counts, stop reasons, tool names, durations, the data
scope, the query log id and the request id. Not the question, the answer, the documents or the
query results: those are bank data, and a trace backend is not where they belong. The audit log
holds them, and the query log id on the span leads there.
"""

from collections.abc import AsyncGenerator, AsyncIterator, Mapping
from typing import Any

import structlog
from opentelemetry import context, trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor, SpanExporter
from opentelemetry.semconv.attributes import db_attributes as db
from opentelemetry.trace import Span, SpanKind, Status, StatusCode
from opentelemetry.util.types import AttributeValue
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine

from finql import __version__
from finql.core.config import Settings

logger = structlog.get_logger(__name__)

tracer = trace.get_tracer("finql", __version__)

# Paths without a trace: probes and static files would only bury the requests that matter.
EXCLUDED_URLS = "health,ready,static/.*"

_provider: TracerProvider | None = None


def configure_telemetry(settings: Settings, *, exporter: SpanExporter | None = None) -> bool:
    """Set up tracing once per process; True if it is on. `exporter`: tests pass an in-memory one.

    The tracer provider is global in OpenTelemetry and can be set only once, so a second call
    (a second app in the same process, or the MCP server) reuses the first setup.
    """
    global _provider
    if _provider is not None:
        return True
    if exporter is None:
        if not settings.otel_endpoint:  # unset, or empty (Compose passes "" when it is off)
            return False
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        exporter = OTLPSpanExporter(endpoint=f"{settings.otel_endpoint.rstrip('/')}/v1/traces")
        processor: SimpleSpanProcessor | BatchSpanProcessor = BatchSpanProcessor(exporter)
    else:
        processor = SimpleSpanProcessor(exporter)  # tests: every span at once, in order

    resource = Resource.create(
        {
            "service.name": settings.otel_service_name,
            "service.version": __version__,
            "deployment.environment.name": settings.env,
        }
    )
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(processor)
    trace.set_tracer_provider(provider)
    _provider = provider
    logger.info("tracing on", endpoint=settings.otel_endpoint, service=settings.otel_service_name)
    return True


def telemetry_enabled() -> bool:
    return _provider is not None


def trace_engine(engine: AsyncEngine) -> None:
    """One span per statement on this engine: the SQL text, never the bound parameters.

    Our own listener on SQLAlchemy's cursor events, not the OpenTelemetry instrumentation
    package: that one supports SQLAlchemy below 2.1 only, and with 2.1 it silently traces
    nothing. The LLM's SQL reads the PII-free analytics views, and the application's own
    statements carry their values as parameters, so the text holds no bank data.
    """
    sync_engine = engine.sync_engine
    database = sync_engine.url.database or ""

    # The span lives on the execution context: one per statement, gone with it, so an
    # interrupted statement cannot leave a span behind on a pooled connection.
    @event.listens_for(sync_engine, "before_cursor_execute")
    def start(conn: Any, cursor: Any, statement: str, params: Any, ctx: Any, many: bool) -> None:
        operation = statement.split(None, 1)[0].upper() if statement.strip() else "SQL"
        ctx.finql_span = tracer.start_span(
            f"{operation} {database}",
            kind=SpanKind.CLIENT,
            attributes={
                db.DB_SYSTEM_NAME: "postgresql",
                db.DB_NAMESPACE: database,
                db.DB_OPERATION_NAME: operation,
                db.DB_QUERY_TEXT: statement,
            },
        )

    @event.listens_for(sync_engine, "after_cursor_execute")
    def end(conn: Any, cursor: Any, statement: str, params: Any, ctx: Any, many: bool) -> None:
        span = getattr(ctx, "finql_span", None)
        if span is not None:
            span.end()

    @event.listens_for(sync_engine, "handle_error")
    def failed(exception_context: Any) -> None:
        span = getattr(exception_context.execution_context, "finql_span", None)
        if span is None:
            return
        error = exception_context.original_exception
        sqlstate = getattr(error, "sqlstate", None)
        if sqlstate:
            span.set_attribute(db.DB_RESPONSE_STATUS_CODE, sqlstate)
        span.set_status(Status(StatusCode.ERROR, type(error).__name__))
        span.end()


def shutdown_telemetry() -> None:
    """Flush the spans still in the batch: at process exit, or they are lost."""
    if _provider is not None:
        _provider.force_flush()


async def traced_stream[T](
    span: Span, stream: AsyncIterator[T], *, error_on: type[BaseException] = Exception
) -> AsyncGenerator[T]:
    """Run an async generator inside `span`, and end the span when the generator ends.

    A `with start_as_current_span()` around a `yield` would leave the span current in whatever
    runs between the steps (the web server, another request). Here the span is current only
    while the generator itself runs: attached before each step and detached right after, in the
    same task. Spans opened inside the generator (model calls, tools) nest under it.
    """
    ctx = trace.set_span_in_context(span)
    try:
        while True:
            token = context.attach(ctx)
            try:
                item = await anext(stream)
            except StopAsyncIteration:
                break
            finally:
                context.detach(token)
            yield item
    except error_on as exc:
        span.record_exception(exc)
        span.set_status(Status(StatusCode.ERROR, type(exc).__name__))
        raise
    finally:
        span.end()
        await _close(stream)


async def _close(stream: AsyncIterator[Any]) -> None:
    aclose = getattr(stream, "aclose", None)
    if aclose is not None:
        await aclose()


def set_attributes(attributes: Mapping[str, AttributeValue | None]) -> None:
    """On the current span, skipping the unknown (None) values."""
    span = trace.get_current_span()
    span.set_attributes({k: v for k, v in attributes.items() if v is not None})


def mark_error(description: str) -> None:
    """The current span failed, without an exception (a rejected SQL, a tool error result)."""
    trace.get_current_span().set_status(Status(StatusCode.ERROR, description))


def log_trace_ids(_: Any, __: str, event: dict[str, Any]) -> dict[str, Any]:
    """structlog processor: the trace and span id on every log line written inside a span, so a
    log line leads to its trace and back."""
    span_context = trace.get_current_span().get_span_context()
    if span_context.is_valid:
        event["trace_id"] = format(span_context.trace_id, "032x")
        event["span_id"] = format(span_context.span_id, "016x")
    return event

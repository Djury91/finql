"""The tracing helpers (core/telemetry.py), on a local tracer provider: no global state."""

from collections.abc import AsyncIterator, Iterator

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from finql.core.telemetry import log_trace_ids, traced_stream


@pytest.fixture
def spans() -> Iterator[tuple[trace.Tracer, InMemorySpanExporter]]:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    yield provider.get_tracer("test"), exporter
    provider.shutdown()


def by_name(finished: tuple[ReadableSpan, ...]) -> dict[str, ReadableSpan]:
    return {span.name: span for span in finished}


async def test_spans_inside_the_stream_nest_under_it_and_nothing_leaks_between_steps(
    spans: tuple[trace.Tracer, InMemorySpanExporter],
) -> None:
    tracer, exporter = spans

    async def turn() -> AsyncIterator[int]:
        for step in range(2):
            with tracer.start_as_current_span(f"step {step}"):
                pass
            yield step

    outside: list[bool] = []
    async for _ in traced_stream(tracer.start_span("turn"), turn()):
        # Between the steps the caller runs: the turn's span must not be current here.
        outside.append(trace.get_current_span().get_span_context().is_valid)

    finished = by_name(exporter.get_finished_spans())
    turn_id = finished["turn"].context.span_id
    assert finished["step 0"].parent is not None and finished["step 0"].parent.span_id == turn_id
    assert finished["step 1"].parent is not None and finished["step 1"].parent.span_id == turn_id
    assert outside == [False, False]


async def test_a_stream_closed_early_still_ends_its_span_and_closes_the_generator(
    spans: tuple[trace.Tracer, InMemorySpanExporter],
) -> None:
    tracer, exporter = spans
    closed: list[bool] = []

    async def endless() -> AsyncIterator[int]:
        try:
            while True:
                yield 1
        finally:
            closed.append(True)

    stream = traced_stream(tracer.start_span("turn"), endless())
    await anext(stream)
    await stream.aclose()  # the client went away mid-stream

    assert closed == [True]
    assert [span.name for span in exporter.get_finished_spans()] == ["turn"]


async def test_an_error_in_the_stream_marks_the_span_and_is_raised(
    spans: tuple[trace.Tracer, InMemorySpanExporter],
) -> None:
    tracer, exporter = spans

    async def failing() -> AsyncIterator[int]:
        yield 1
        raise RuntimeError("elromlott")

    with pytest.raises(RuntimeError):
        async for _ in traced_stream(tracer.start_span("turn"), failing()):
            pass

    (span,) = exporter.get_finished_spans()
    assert span.status.status_code is StatusCode.ERROR
    assert [event.name for event in span.events] == ["exception"]


def test_log_lines_inside_a_span_carry_its_ids(
    spans: tuple[trace.Tracer, InMemorySpanExporter],
) -> None:
    tracer, _ = spans

    assert "trace_id" not in log_trace_ids(None, "info", {"event": "kint"})
    with tracer.start_as_current_span("kérés") as span:
        event = log_trace_ids(None, "info", {"event": "bent"})

    assert event["trace_id"] == format(span.get_span_context().trace_id, "032x")
    assert event["span_id"] == format(span.get_span_context().span_id, "016x")

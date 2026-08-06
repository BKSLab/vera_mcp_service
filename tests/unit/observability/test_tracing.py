from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from opentelemetry import propagate, trace
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from app.clients.rag_client import RagClient
from app.core.settings import ObservabilitySettings, RagClientSettings
from app.observability.tracing import (
    _add_exporter,
    _create_otlp_exporter,
    get_tracer,
    reset_for_tests,
    shutdown_tracing,
)
from app.schemas.consultation import ConsultationSendSuccess
from app.tools.send_consultation_email import register_send_consultation_email
from app.tools.vera_rag_kb import register_vera_rag_kb

_exporter = InMemorySpanExporter()
reset_for_tests(_exporter)


@pytest.fixture(autouse=True)
def _clear_spans():
    _exporter.clear()
    yield


def _settings() -> RagClientSettings:
    return RagClientSettings(
        rag_service_url='http://rag.test',
        rag_service_api_key='test-api-key',
        rag_search_timeout_seconds=5.0,
        rag_search_top_k=5,
    )


def _rag_client(handler) -> RagClient:
    httpx_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return RagClient(httpx_client=httpx_client, settings=_settings())


def _mcp(handler) -> FastMCP:
    mcp = FastMCP('test-tracing')
    register_vera_rag_kb(mcp, _rag_client(handler), top_k=5)
    return mcp


def _finished_span(name: str):
    return next(span for span in _exporter.get_finished_spans() if span.name == name)


async def test_direct_call_creates_only_mcp_span_with_safe_success_attributes():
    mcp = _mcp(lambda request: httpx.Response(200, json={'chunks': [{'chunk_id': 'c1'}]}))

    await mcp.call_tool('vera_rag_kb', {'query': 'sensitive query'})

    spans = _exporter.get_finished_spans()
    assert [span.name for span in spans] == ['mcp.execute.vera_rag_kb']
    span = spans[0]
    assert span.attributes['openinference.span.kind'] == 'TOOL'
    assert 'mcp.tool.audience' not in span.attributes
    assert span.attributes['mcp.tool.query_length'] == len('sensitive query')
    assert span.attributes['mcp.tool.result_chunk_count'] == 1
    assert span.attributes['mcp.tool.outcome'] == 'ok'
    assert 'sensitive query' not in str(span.attributes)


async def test_empty_result_is_not_error():
    mcp = _mcp(lambda request: httpx.Response(200, json={'chunks': []}))

    await mcp.call_tool('vera_rag_kb', {'query': 'q'})

    span = _finished_span('mcp.execute.vera_rag_kb')
    assert span.attributes['mcp.tool.outcome'] == 'empty'
    assert span.status.status_code is StatusCode.UNSET


async def test_rag_unavailable_records_error_and_preserves_tool_contract():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError('unavailable', request=request)

    mcp = _mcp(handler)

    with pytest.raises(ToolError, match='unavailable'):
        await mcp.call_tool('vera_rag_kb', {'query': 'q'})

    span = _finished_span('mcp.execute.vera_rag_kb')
    assert span.attributes['mcp.tool.outcome'] == 'rag_unavailable'
    assert span.status.status_code is StatusCode.ERROR


async def test_incoming_context_is_parent_and_outgoing_rag_header_uses_mcp_span():
    outgoing = {}

    def handler(request: httpx.Request) -> httpx.Response:
        outgoing.update(request.headers)
        return httpx.Response(200, json={'chunks': []})

    mcp = _mcp(handler)
    (registered_tool,) = mcp._tool_manager._tools.values()
    carrier = {}
    with get_tracer().start_as_current_span('agent.tool') as agent_span:
        agent_context = agent_span.get_span_context()
        propagate.inject(carrier)

    fake_context = SimpleNamespace(
        request_context=SimpleNamespace(request=SimpleNamespace(headers=carrier))
    )
    await registered_tool.fn(query='q', ctx=fake_context)

    mcp_span = _finished_span('mcp.execute.vera_rag_kb')
    assert mcp_span.context.trace_id == agent_context.trace_id
    assert mcp_span.parent.span_id == agent_context.span_id
    assert mcp_span.parent.is_remote is True
    propagated = trace.get_current_span(propagate.extract(outgoing)).get_span_context()
    assert propagated.trace_id == mcp_span.context.trace_id
    assert propagated.span_id == mcp_span.context.span_id


async def test_context_parameter_is_absent_from_public_schema():
    mcp = _mcp(lambda request: httpx.Response(200, json={'chunks': []}))

    (tool,) = await mcp.list_tools()

    assert set(tool.inputSchema['properties']) == {'query'}


async def test_consultation_span_contains_no_text_or_email():
    sensitive_text = 'PRIVATE CONSULTATION TEXT'
    sensitive_email = 'private-user@example.com'
    delivery_service = AsyncMock()
    delivery_service.send.return_value = ConsultationSendSuccess(
        email=sensitive_email,
        document_name='consultation.pdf',
    )
    mcp = FastMCP('test-consultation-tracing')
    register_send_consultation_email(mcp, delivery_service)

    await mcp.call_tool(
        'send_consultation_email',
        {
            'consultation_text': sensitive_text,
            'consultation_topic': 'PRIVATE CONSULTATION TOPIC',
            'email': sensitive_email,
        },
    )

    span = _finished_span('mcp.execute.send_consultation_email')
    attributes = str(span.attributes)
    assert span.attributes['consultation.input_length'] == len(sensitive_text)
    assert span.attributes['consultation.topic_length'] == len(
        'PRIVATE CONSULTATION TOPIC'
    )
    assert span.attributes['consultation.outcome'] == 'ok'
    assert sensitive_text not in attributes
    assert sensitive_email not in attributes
    assert 'PRIVATE CONSULTATION TOPIC' not in attributes


async def test_consultation_span_uses_incoming_trace_context():
    delivery_service = AsyncMock()
    delivery_service.send.return_value = ConsultationSendSuccess(
        email='user@example.com',
        document_name='consultation.pdf',
    )
    mcp = FastMCP('test-consultation-tracing')
    register_send_consultation_email(mcp, delivery_service)
    (registered_tool,) = mcp._tool_manager._tools.values()
    carrier = {}

    with get_tracer().start_as_current_span('agent.consultation') as agent_span:
        agent_context = agent_span.get_span_context()
        propagate.inject(carrier)

    fake_context = SimpleNamespace(
        request_context=SimpleNamespace(request=SimpleNamespace(headers=carrier))
    )
    await registered_tool.fn(
        consultation_text='Текст.',
        consultation_topic='Трудовые права',
        email='user@example.com',
        ctx=fake_context,
    )

    mcp_span = _finished_span('mcp.execute.send_consultation_email')
    assert mcp_span.context.trace_id == agent_context.trace_id
    assert mcp_span.parent.span_id == agent_context.span_id
    assert mcp_span.parent.is_remote is True


def test_exporter_uses_shared_phoenix_project_header(monkeypatch):
    calls = {}

    class _Exporter:
        def __init__(self, **kwargs):
            calls.update(kwargs)

    monkeypatch.setattr('app.observability.tracing.OTLPSpanExporter', _Exporter)

    _create_otlp_exporter(
        ObservabilitySettings(
            phoenix_otlp_endpoint='http://phoenix:6006/v1/traces',
            phoenix_project_name='vera-testing',
        )
    )

    assert calls['headers'] == {'x-project-name': 'vera-testing'}


def test_disabled_phoenix_does_not_add_exporter(monkeypatch):
    class _Provider:
        def add_span_processor(self, processor):
            raise AssertionError('processor must not be added')

    monkeypatch.setattr(
        'app.observability.tracing._create_otlp_exporter',
        lambda settings: (_ for _ in ()).throw(AssertionError('exporter must not be created')),
    )

    _add_exporter(_Provider(), ObservabilitySettings(phoenix_enabled=False))


def test_shutdown_force_flushes_once_and_is_idempotent(monkeypatch):
    calls = []

    class _Provider:
        def force_flush(self, timeout_millis: int):
            calls.append(('flush', timeout_millis))
            return True

        def shutdown(self):
            calls.append(('shutdown', None))

    monkeypatch.setattr('app.observability.tracing._provider', _Provider())
    monkeypatch.setattr('app.observability.tracing._shutdown', False)

    shutdown_tracing()
    shutdown_tracing()

    assert calls == [('flush', 10_000), ('shutdown', None)]

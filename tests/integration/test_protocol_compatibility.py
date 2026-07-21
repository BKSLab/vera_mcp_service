"""Верификация протокола ошибок MCP против настоящего streamable-http
сервера этого сервиса и настоящего `MultiServerMCPClient`
(MCP_SERVICE_PLAN.md, Этап 3).

Не "фича", а проверка того, что уже зафиксировано в разделе 0.1 контракта:
Agent Service ждёт исключение MCP-уровня при сбое, не `dict` с полем
ошибки — и это нужно подтвердить эмпирически против настоящего
MCP/streamable-http протокола, не только юнит-тестом на уровне Python-функции
(tests/unit/tools/test_vera_rag_kb.py, Этап 2).
"""

import asyncio
import json
import socket
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import httpx
import pytest
import uvicorn
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.interceptors import (
    MCPToolCallRequest,
    MCPToolCallResult,
)
from langchain_mcp_adapters.tools import _MCPToolExecutionError
from mcp.server.fastmcp import FastMCP
from opentelemetry import propagate, trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from sse_starlette.sse import AppStatus

from app.clients.rag_client import RagClient
from app.core.settings import RagClientSettings
from app.observability.tracing import get_tracer, reset_for_tests
from app.tools import register_all_tools


def _rag_client_settings() -> RagClientSettings:
    return RagClientSettings(
        rag_service_url='http://rag.test',
        rag_service_api_key='test-api-key',
        rag_search_timeout_seconds=5.0,
        rag_search_top_k=5,
    )


def _build_mcp_app(rag_handler) -> object:
    """Собирает настоящий FastMCP этого сервиса (`register_all_tools`), с
    `RagClient`, у которого подменён только транспорт HTTP-клиента
    (`httpx.MockTransport`) — сам MCP/streamable-http путь до тула реальный,
    мокается только сетевой вызов к RAG Service (по аналогии с Этапом 1).
    """
    httpx_client = httpx.AsyncClient(transport=httpx.MockTransport(rag_handler))
    rag_client = RagClient(httpx_client=httpx_client, settings=_rag_client_settings())

    mcp = FastMCP('vera-tools', stateless_http=True)
    register_all_tools(mcp, rag_client=rag_client, rag_top_k=5)
    return mcp.streamable_http_app()


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as temp_socket:
        temp_socket.bind(('127.0.0.1', 0))
        return temp_socket.getsockname()[1]


@asynccontextmanager
async def _run_server(app: object) -> AsyncIterator[str]:
    """Запускает настоящий сервер этого сервиса на свободном локальном
    порту и отдаёт MCP-URL.

    **Находка, перепроверенная для этого репозитория (см. MCP_SERVICE_PLAN.md,
    раздел 0.2 — оригинально найдено в `vera_agent_service/tests/fixtures/
    mock_mcp_server.py`):** `mcp` SDK использует `sse_starlette.EventSourceResponse`
    внутри streamable-http транспорта тоже, не только в чистом SSE. Без
    сброса `AppStatus.should_exit = False` в `finally` второй поднятый в
    одном процессе сервер вешает клиента на `initialize`.
    """
    port = _free_port()
    config = uvicorn.Config(app, host='127.0.0.1', port=port, log_level='warning')
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve())
    try:
        while not server.started:
            await asyncio.sleep(0.02)
        yield f'http://127.0.0.1:{port}/mcp'
    finally:
        server.should_exit = True
        await server_task
        AppStatus.should_exit = False


def _parse_tool_result(raw_result: object) -> dict:
    """Разбирает результат `tool.ainvoke(...)` в обычный `dict`.

    Успешный вызов через `langchain-mcp-adapters` возвращает список
    content-блоков (`[{"type": "text", "text": "<json>", "id": "..."}]`),
    не сырой `dict` напрямую — подтверждено эмпирически тем же способом,
    каким это уже задокументировано на стороне Agent Service
    (`_parse_tool_result`, `vera_agent_service/app/clients/mcp_client.py:173-189`).
    Не специфика этого сервиса — общее поведение протокола/адаптера.
    """
    assert isinstance(raw_result, list) and raw_result, f'Неожиданный формат ответа: {raw_result!r}'
    return json.loads(raw_result[0]['text'])


async def _inject_trace_context(
    request: MCPToolCallRequest,
    handler: Callable[[MCPToolCallRequest], Awaitable[MCPToolCallResult]],
) -> MCPToolCallResult:
    headers = dict(request.headers or {})
    propagate.inject(headers)
    return await handler(request.override(headers=headers))


def _mcp_client(url: str, with_tracing: bool = False) -> MultiServerMCPClient:
    return MultiServerMCPClient(
        {
            'vera-tools': {
                'url': url,
                'transport': 'streamable_http',
                'timeout': 5.0,
            }
        },
        handle_tool_errors=False,
        tool_interceptors=[_inject_trace_context] if with_tracing else None,
    )


def _attach_exporter() -> InMemorySpanExporter:
    exporter = InMemorySpanExporter()
    provider = trace.get_tracer_provider()
    if isinstance(provider, TracerProvider):
        provider.add_span_processor(SimpleSpanProcessor(exporter))
    else:
        reset_for_tests(exporter)
    return exporter


async def test_kb_search_returns_dict_with_chunks_on_success():
    def rag_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={'chunks': [{'chunk_id': 'c1', 'text': 'квота 2%'}]})

    app = _build_mcp_app(rag_handler)
    async with _run_server(app) as url:
        client = _mcp_client(url)
        tools = await client.get_tools()
        (kb_search,) = [tool for tool in tools if tool.name == 'vera_rag_kb']

        result = await kb_search.ainvoke({'query': 'квота', 'audience': 'both'})

        assert _parse_tool_result(result) == {'chunks': [{'chunk_id': 'c1', 'text': 'квота 2%'}]}


async def test_kb_search_returns_empty_chunks_as_valid_result_not_error():
    def rag_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={'chunks': []})

    app = _build_mcp_app(rag_handler)
    async with _run_server(app) as url:
        client = _mcp_client(url)
        tools = await client.get_tools()
        (kb_search,) = [tool for tool in tools if tool.name == 'vera_rag_kb']

        result = await kb_search.ainvoke({'query': 'непонятный вопрос', 'audience': 'both'})

        assert _parse_tool_result(result) == {'chunks': []}


async def test_kb_search_raises_exception_not_error_dict_when_rag_unreachable():
    def rag_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError('connection refused', request=request)

    app = _build_mcp_app(rag_handler)
    async with _run_server(app) as url:
        client = _mcp_client(url)
        tools = await client.get_tools()
        (kb_search,) = [tool for tool in tools if tool.name == 'vera_rag_kb']

        with pytest.raises(_MCPToolExecutionError):
            await kb_search.ainvoke({'query': 'квота', 'audience': 'both'})


async def test_kb_search_raises_exception_not_error_dict_when_rag_returns_500():
    def rag_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={'detail': 'embedding API unavailable'})

    app = _build_mcp_app(rag_handler)
    async with _run_server(app) as url:
        client = _mcp_client(url)
        tools = await client.get_tools()
        (kb_search,) = [tool for tool in tools if tool.name == 'vera_rag_kb']

        with pytest.raises(_MCPToolExecutionError):
            await kb_search.ainvoke({'query': 'квота', 'audience': 'both'})


async def test_streamable_http_preserves_isolated_trace_context_to_mcp_and_rag():
    exporter = _attach_exporter()
    outgoing_rag_headers: dict[str, dict[str, str]] = {}

    def rag_handler(request: httpx.Request) -> httpx.Response:
        query = json.loads(request.content)['query']
        outgoing_rag_headers[query] = dict(request.headers)
        return httpx.Response(200, json={'chunks': []})

    app = _build_mcp_app(rag_handler)
    async with _run_server(app) as url:
        client = _mcp_client(url, with_tracing=True)
        tools = await client.get_tools()
        (kb_search,) = [tool for tool in tools if tool.name == 'vera_rag_kb']
        parent_contexts = {}

        async def call(query: str) -> None:
            with get_tracer().start_as_current_span(f'agent.{query}') as parent:
                parent_contexts[query] = parent.get_span_context()
                await kb_search.ainvoke({'query': query, 'audience': 'both'})

        await asyncio.gather(call('first'), call('second'))

    mcp_spans = [
        span
        for span in exporter.get_finished_spans()
        if span.name == 'mcp.execute.vera_rag_kb'
    ]
    assert len(mcp_spans) == 2
    assert {span.context.trace_id for span in mcp_spans} == {
        context.trace_id for context in parent_contexts.values()
    }
    assert {span.parent.span_id for span in mcp_spans} == {
        context.span_id for context in parent_contexts.values()
    }

    for query, headers in outgoing_rag_headers.items():
        propagated = trace.get_current_span(propagate.extract(headers)).get_span_context()
        assert propagated.trace_id == parent_contexts[query].trace_id
        matching_mcp_span = next(
            span for span in mcp_spans if span.context.trace_id == propagated.trace_id
        )
        assert propagated.span_id == matching_mcp_span.context.span_id

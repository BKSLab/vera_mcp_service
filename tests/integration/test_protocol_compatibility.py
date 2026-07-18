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
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import pytest
import uvicorn
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import _MCPToolExecutionError
from mcp.server.fastmcp import FastMCP
from sse_starlette.sse import AppStatus

from app.clients.rag_client import RagClient
from app.core.settings import RagClientSettings
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


def _mcp_client(url: str) -> MultiServerMCPClient:
    return MultiServerMCPClient(
        {
            'vera-tools': {
                'url': url,
                'transport': 'streamable_http',
                'timeout': 5.0,
            }
        },
        handle_tool_errors=False,
    )


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

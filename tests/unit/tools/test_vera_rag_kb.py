import asyncio
import json
from unittest.mock import AsyncMock

import httpx
import pytest
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from app.clients.rag_client import RagClient
from app.core.settings import RagClientSettings
from app.exceptions.rag import RagUnavailableError
from app.tools.vera_rag_kb import register_vera_rag_kb


def _mcp_with_fake_rag_client(rag_client: AsyncMock, top_k: int = 5) -> FastMCP:
    mcp = FastMCP('test-kb-search')
    register_vera_rag_kb(mcp, rag_client, top_k=top_k)
    return mcp


async def test_kb_search_calls_rag_client_with_expected_arguments():
    rag_client = AsyncMock()
    rag_client.search.return_value = {'chunks': []}
    mcp = _mcp_with_fake_rag_client(rag_client, top_k=7)

    await mcp.call_tool('vera_rag_kb', {'query': 'квота на трудоустройство', 'audience': 'employer'})

    rag_client.search.assert_called_once_with(query='квота на трудоустройство', audience='employer', top_k=7)


async def test_kb_search_defaults_audience_to_both():
    rag_client = AsyncMock()
    rag_client.search.return_value = {'chunks': []}
    mcp = _mcp_with_fake_rag_client(rag_client)

    await mcp.call_tool('vera_rag_kb', {'query': 'квота'})

    rag_client.search.assert_called_once_with(query='квота', audience='both', top_k=5)


async def test_kb_search_returns_rag_client_result():
    rag_client = AsyncMock()
    rag_client.search.return_value = {'chunks': [{'chunk_id': 'c1', 'text': 'квота 2%'}]}
    mcp = _mcp_with_fake_rag_client(rag_client)

    result = await mcp.call_tool('vera_rag_kb', {'query': 'квота'})

    payload = json.loads(result[0].text)
    assert payload == {'chunks': [{'chunk_id': 'c1', 'text': 'квота 2%'}]}


async def test_kb_search_returns_empty_chunks_as_valid_result():
    rag_client = AsyncMock()
    rag_client.search.return_value = {'chunks': []}
    mcp = _mcp_with_fake_rag_client(rag_client)

    result = await mcp.call_tool('vera_rag_kb', {'query': 'непонятный вопрос'})

    assert json.loads(result[0].text) == {'chunks': []}


async def test_kb_search_rejects_empty_query_before_calling_rag_client():
    rag_client = AsyncMock()
    mcp = _mcp_with_fake_rag_client(rag_client)

    with pytest.raises(ToolError):
        await mcp.call_tool('vera_rag_kb', {'query': ''})

    rag_client.search.assert_not_called()


async def test_kb_search_rejects_invalid_audience_before_calling_rag_client():
    rag_client = AsyncMock()
    mcp = _mcp_with_fake_rag_client(rag_client)

    with pytest.raises(ToolError):
        await mcp.call_tool('vera_rag_kb', {'query': 'квота', 'audience': 'not_a_valid_audience'})

    rag_client.search.assert_not_called()


async def test_kb_search_propagates_rag_unavailable_error_not_swallowed_into_dict():
    rag_client = AsyncMock()
    rag_client.search.side_effect = RagUnavailableError('RAG Service unreachable')
    mcp = _mcp_with_fake_rag_client(rag_client)

    with pytest.raises(ToolError, match='RAG Service'):
        await mcp.call_tool('vera_rag_kb', {'query': 'квота'})


async def test_register_vera_rag_kb_registers_expected_tool_name():
    rag_client = AsyncMock()
    mcp = _mcp_with_fake_rag_client(rag_client)

    tools = await mcp.list_tools()

    assert {tool.name for tool in tools} == {'vera_rag_kb'}


async def test_register_vera_rag_kb_sets_non_empty_description():
    rag_client = AsyncMock()
    mcp = _mcp_with_fake_rag_client(rag_client)

    tools = await mcp.list_tools()
    (vera_rag_kb_tool,) = tools

    assert vera_rag_kb_tool.description
    assert 'audience' in vera_rag_kb_tool.description
    assert 'Трудовой кодекс РФ' in vera_rag_kb_tool.description
    assert 'федеральные законы' in vera_rag_kb_tool.description
    assert 'постановления Правительства РФ' in vera_rag_kb_tool.description
    assert 'постановления Верховного Суда РФ' in vera_rag_kb_tool.description
    assert 'авторские публикации' in vera_rag_kb_tool.description


async def test_concurrent_kb_search_calls_do_not_share_state():
    """Дёшево поставить сейчас как привычку/шаблон для будущих тулов —
    дороже добавлять после первого бага с shared mutable state в новом
    тule (MCP_SERVICE_PLAN.md, Этап 6.5)."""

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        query = body['query']
        return httpx.Response(200, json={'chunks': [{'chunk_id': query}]})

    httpx_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    settings = RagClientSettings(
        rag_service_url='http://rag.test',
        rag_service_api_key='test-api-key',
        rag_search_timeout_seconds=5.0,
        rag_search_top_k=5,
    )
    rag_client = RagClient(httpx_client=httpx_client, settings=settings)
    mcp = _mcp_with_fake_rag_client(rag_client)

    queries = [f'query-{i}' for i in range(20)]
    results = await asyncio.gather(*(mcp.call_tool('vera_rag_kb', {'query': q}) for q in queries))

    parsed = [json.loads(result[0].text) for result in results]
    assert [payload['chunks'][0]['chunk_id'] for payload in parsed] == queries

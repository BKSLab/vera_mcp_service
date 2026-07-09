import json
from unittest.mock import AsyncMock

import pytest
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from app.exceptions.rag import RagUnavailableError
from app.tools.kb_search import register_kb_search


def _mcp_with_fake_rag_client(rag_client: AsyncMock, top_k: int = 5) -> FastMCP:
    mcp = FastMCP('test-kb-search')
    register_kb_search(mcp, rag_client, top_k=top_k)
    return mcp


async def test_kb_search_calls_rag_client_with_expected_arguments():
    rag_client = AsyncMock()
    rag_client.search.return_value = {'chunks': []}
    mcp = _mcp_with_fake_rag_client(rag_client, top_k=7)

    await mcp.call_tool('kb_search', {'query': 'квота на трудоустройство', 'audience': 'employer'})

    rag_client.search.assert_called_once_with(query='квота на трудоустройство', audience='employer', top_k=7)


async def test_kb_search_defaults_audience_to_both():
    rag_client = AsyncMock()
    rag_client.search.return_value = {'chunks': []}
    mcp = _mcp_with_fake_rag_client(rag_client)

    await mcp.call_tool('kb_search', {'query': 'квота'})

    rag_client.search.assert_called_once_with(query='квота', audience='both', top_k=5)


async def test_kb_search_returns_rag_client_result():
    rag_client = AsyncMock()
    rag_client.search.return_value = {'chunks': [{'chunk_id': 'c1', 'text': 'квота 2%'}]}
    mcp = _mcp_with_fake_rag_client(rag_client)

    result = await mcp.call_tool('kb_search', {'query': 'квота'})

    payload = json.loads(result[0].text)
    assert payload == {'chunks': [{'chunk_id': 'c1', 'text': 'квота 2%'}]}


async def test_kb_search_returns_empty_chunks_as_valid_result():
    rag_client = AsyncMock()
    rag_client.search.return_value = {'chunks': []}
    mcp = _mcp_with_fake_rag_client(rag_client)

    result = await mcp.call_tool('kb_search', {'query': 'непонятный вопрос'})

    assert json.loads(result[0].text) == {'chunks': []}


async def test_kb_search_rejects_empty_query_before_calling_rag_client():
    rag_client = AsyncMock()
    mcp = _mcp_with_fake_rag_client(rag_client)

    with pytest.raises(ToolError):
        await mcp.call_tool('kb_search', {'query': ''})

    rag_client.search.assert_not_called()


async def test_kb_search_rejects_invalid_audience_before_calling_rag_client():
    rag_client = AsyncMock()
    mcp = _mcp_with_fake_rag_client(rag_client)

    with pytest.raises(ToolError):
        await mcp.call_tool('kb_search', {'query': 'квота', 'audience': 'not_a_valid_audience'})

    rag_client.search.assert_not_called()


async def test_kb_search_propagates_rag_unavailable_error_not_swallowed_into_dict():
    rag_client = AsyncMock()
    rag_client.search.side_effect = RagUnavailableError('RAG Service unreachable')
    mcp = _mcp_with_fake_rag_client(rag_client)

    with pytest.raises(ToolError, match='RAG Service'):
        await mcp.call_tool('kb_search', {'query': 'квота'})


async def test_register_kb_search_registers_tool_named_kb_search():
    rag_client = AsyncMock()
    mcp = _mcp_with_fake_rag_client(rag_client)

    tools = await mcp.list_tools()

    assert {tool.name for tool in tools} == {'kb_search'}


async def test_register_kb_search_sets_non_empty_description():
    rag_client = AsyncMock()
    mcp = _mcp_with_fake_rag_client(rag_client)

    tools = await mcp.list_tools()
    (kb_search_tool,) = tools

    assert kb_search_tool.description
    assert 'audience' in kb_search_tool.description

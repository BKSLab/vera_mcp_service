from unittest.mock import AsyncMock

from mcp.server.fastmcp import FastMCP

from app.tools import register_all_tools

EXPECTED_TOOL_NAMES = {'vera_rag_kb'}
"""Единственное место, которое обязательно нужно обновить при добавлении
нового тула (MCP_SERVICE_PLAN.md, раздел 0.3 — meta-тест реестра тулов)."""


async def test_register_all_tools_registers_exactly_expected_tool_names():
    mcp = FastMCP('test-registry')

    register_all_tools(mcp, rag_client=AsyncMock(), rag_top_k=5)

    tools = await mcp.list_tools()
    assert {tool.name for tool in tools} == EXPECTED_TOOL_NAMES


async def test_register_all_tools_has_no_duplicate_names():
    mcp = FastMCP('test-registry')

    register_all_tools(mcp, rag_client=AsyncMock(), rag_top_k=5)

    tools = await mcp.list_tools()
    names = [tool.name for tool in tools]
    assert len(names) == len(set(names))


async def test_register_all_tools_every_tool_has_non_empty_description():
    mcp = FastMCP('test-registry')

    register_all_tools(mcp, rag_client=AsyncMock(), rag_top_k=5)

    tools = await mcp.list_tools()
    assert all(tool.description for tool in tools)

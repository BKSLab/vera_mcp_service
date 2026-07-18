from mcp.server.fastmcp import FastMCP

from app.clients.rag_client import RagClient
from app.tools.vera_rag_kb import register_vera_rag_kb


def register_all_tools(mcp: FastMCP, rag_client: RagClient, rag_top_k: int) -> None:
    """Регистрирует все MCP-инструменты этого сервиса.

    Единственное место, которое трогают при добавлении нового тула
    (MCP_SERVICE_PLAN.md, раздел 0.1 — реестр тулов, паттерн `tools-mcp`).
    Итерация 1 — один тул; итерация 2 добавит сюда
    `register_get_user_favorites(mcp, ...)`, `register_search_vacancies(mcp, ...)` и т.д.
    """
    register_vera_rag_kb(mcp, rag_client, top_k=rag_top_k)

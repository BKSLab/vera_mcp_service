import logging
from typing import Annotated, Literal

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from app.clients.rag_client import RagClient
from app.observability.tracing import get_tracer

logger = logging.getLogger('vera_mcp_service')
tracer = get_tracer()

KB_SEARCH_DESCRIPTION = (
    "Поиск по базе знаний о правах людей с инвалидностью в сфере "
    "трудоустройства и трудовой деятельности (ТК РФ, ФЗ-181, авторские статьи). "
    "query — текст запроса пользователя; "
    "audience — целевая аудитория: 'seeker' (соискатель), 'employer' (работодатель) "
    "или 'both' (не уточнено, по умолчанию). "
    "Возвращает словарь с полем chunks — список релевантных фрагментов с источником; "
    "пустой список означает, что в базе знаний нет ответа на этот вопрос, не ошибку."
)


def register_kb_search(mcp: FastMCP, rag_client: RagClient, top_k: int) -> None:
    """Регистрирует тул `kb_search` на переданном MCP-сервере.

    Args:
        mcp: экземпляр `FastMCP`, на котором регистрируется тул.
        rag_client: клиент RAG Service (собирается на уровне модуля `main.py`, Этап 4).
        top_k: сколько чанков запрашивать у RAG Service (`RagClientSettings.rag_search_top_k`).
    """

    async def kb_search(
        query: Annotated[str, Field(min_length=1)],
        audience: Literal['seeker', 'employer', 'both'] = 'both',
    ) -> dict:
        """Поиск по базе знаний о правах людей с инвалидностью в сфере
        трудоустройства и трудовой деятельности.

        Имя и сигнатура зафиксированы контрактом с Agent Service
        (MCP_SERVICE_PLAN.md, раздел 3.1) — совпадают буквально с локальной
        заглушкой `build_kb_search_tool_proxy` в `vera_agent_service`.

        Raises:
            RagUnavailableError: сеть/таймаут/`5xx`/`429`/неожиданный формат
                ответа RAG Service — пробрасывается как есть, не перехватывается
                здесь (раздел 0.1 — Agent Service ждёт исключение MCP-уровня,
                не `dict` с полем ошибки).
        """
        with tracer.start_as_current_span('mcp.tool_call', attributes={'mcp.tool_name': 'kb_search'}):
            return await rag_client.search(query=query, audience=audience, top_k=top_k)

    mcp.add_tool(kb_search, name='kb_search', description=KB_SEARCH_DESCRIPTION)

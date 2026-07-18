import logging
from typing import Annotated, Literal

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from app.clients.rag_client import RagClient
from app.observability.tracing import get_tracer

logger = logging.getLogger('vera_mcp_service')
tracer = get_tracer()

VERA_RAG_KB_DESCRIPTION = (
    "Юридический поиск по базе знаний Vera о трудоустройстве, трудовых правах "
    "и гарантиях для людей с инвалидностью в Российской Федерации. "
    "База содержит Трудовой кодекс РФ, федеральные законы, постановления "
    "Правительства РФ, постановления Верховного Суда РФ и авторские публикации. "
    "Используй инструмент, когда нужно найти применимую правовую норму, гарантию, "
    "обязанность работодателя, порядок действий или юридическое разъяснение. "
    "query — полный текст юридического вопроса пользователя; "
    "audience — целевая аудитория: 'seeker' (соискатель), 'employer' (работодатель) "
    "или 'both' (не уточнено, по умолчанию). "
    "Возвращает словарь с полем chunks — список релевантных фрагментов юридических "
    "источников с метаданными. Пустой список означает, что база знаний не содержит "
    "подходящего ответа; это не техническая ошибка."
)


def register_vera_rag_kb(mcp: FastMCP, rag_client: RagClient, top_k: int) -> None:
    """Регистрирует тул `vera_rag_kb` на переданном MCP-сервере.

    Args:
        mcp: экземпляр `FastMCP`, на котором регистрируется тул.
        rag_client: клиент RAG Service (собирается на уровне модуля `main.py`, Этап 4).
        top_k: сколько чанков запрашивать у RAG Service (`RagClientSettings.rag_search_top_k`).
    """

    async def vera_rag_kb(
        query: Annotated[str, Field(min_length=1)],
        audience: Literal['seeker', 'employer', 'both'] = 'both',
    ) -> dict:
        """Поиск по базе знаний о правах людей с инвалидностью в сфере
        трудоустройства и трудовой деятельности.

        Публичное имя `vera_rag_kb` и сигнатура являются контрактом с
        Agent Service. Его внутренний proxy пока называется
        `build_kb_search_tool_proxy`, но должен резолвить удалённый тул
        именно по имени `vera_rag_kb`.

        Raises:
            RagUnavailableError: сеть/таймаут/`5xx`/`429`/неожиданный формат
                ответа RAG Service — пробрасывается как есть, не перехватывается
                здесь (раздел 0.1 — Agent Service ждёт исключение MCP-уровня,
                не `dict` с полем ошибки).
        """
        with tracer.start_as_current_span('mcp.tool_call', attributes={'mcp.tool_name': 'vera_rag_kb'}):
            return await rag_client.search(query=query, audience=audience, top_k=top_k)

    mcp.add_tool(vera_rag_kb, name='vera_rag_kb', description=VERA_RAG_KB_DESCRIPTION)

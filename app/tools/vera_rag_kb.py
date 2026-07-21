import logging
from typing import Annotated, Literal

from mcp.server.fastmcp import Context, FastMCP
from opentelemetry.trace import Status, StatusCode
from pydantic import Field

from app.clients.rag_client import RagClient
from app.exceptions.rag import RagUnavailableError
from app.observability.tracing import extract_trace_context, get_tracer

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
        ctx: Context | None = None,
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
        try:
            request_context = ctx.request_context if ctx is not None else None
        except (AttributeError, ValueError):
            request_context = None
        request = getattr(request_context, 'request', None)
        parent_context = extract_trace_context(getattr(request, 'headers', None))
        with tracer.start_as_current_span(
            'mcp.execute.vera_rag_kb',
            context=parent_context,
            attributes={
                'openinference.span.kind': 'TOOL',
                'mcp.server.name': 'vera-tools',
                'mcp.tool.name': 'vera_rag_kb',
                'mcp.tool.audience': audience,
                'mcp.tool.query_length': len(query),
            },
        ) as span:
            try:
                result = await rag_client.search(query=query, audience=audience, top_k=top_k)
            except RagUnavailableError as error:
                span.set_attribute('mcp.tool.result_chunk_count', 0)
                span.set_attribute('mcp.tool.outcome', 'rag_unavailable')
                span.record_exception(error)
                span.set_status(Status(StatusCode.ERROR, str(error)))
                raise
            except Exception as error:
                span.set_attribute('mcp.tool.result_chunk_count', 0)
                span.set_attribute('mcp.tool.outcome', 'error')
                span.record_exception(error)
                span.set_status(Status(StatusCode.ERROR, str(error)))
                raise

            chunks = result.get('chunks', [])
            span.set_attribute('mcp.tool.result_chunk_count', len(chunks))
            span.set_attribute('mcp.tool.outcome', 'ok' if chunks else 'empty')
            return result

    mcp.add_tool(vera_rag_kb, name='vera_rag_kb', description=VERA_RAG_KB_DESCRIPTION)

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.clients.llm import LlmClient
from app.clients.rag_client import RagClient
from app.clients.smtp_client import SmtpClient
from app.core.config_logger import logger
from app.core.settings import get_settings
from app.health import HealthRegistry
from app.observability.tracing import configure_tracing, shutdown_tracing
from app.renderers.consultation_pdf import ConsultationPdfRenderer
from app.services.consultation_delivery import ConsultationDeliveryService
from app.services.consultation_preparation import ConsultationPreparationService
from app.tools import register_all_tools

settings = get_settings()

# Клиент живёт всё время работы ASGI-приложения. Его нельзя закрывать через
# `FastMCP(lifespan=...)`: этот lifecycle относится к низкоуровневой
# MCP-сессии и при `stateless_http=True` завершается после отдельного
# запроса. В результате первая же initialize/list_tools-сессия закрывала
# общий клиент и следующие вызовы тула падали с `client has been closed`.
httpx_client = httpx.AsyncClient()
rag_client = RagClient(httpx_client=httpx_client, settings=settings.rag)
llm_client = LlmClient(
    httpx_client=httpx_client,
    model=settings.llm.consultation_formatting_llm_model,
    url=f'{settings.llm.llm_api_url.rstrip("/")}/chat/completions',
    headers={
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {settings.llm.llm_api_key.get_secret_value()}',
    },
    temperature=settings.llm.llm_temperature,
    timeout=int(settings.llm.llm_timeout_seconds),
    retries=settings.llm.llm_retries,
    delay=settings.llm.llm_retry_base_delay_seconds,
    max_delay=settings.llm.llm_retry_max_delay_seconds,
    use_json_mode=settings.llm.llm_use_json_mode,
    extra_payload={
        'reasoning': {
            'effort': settings.llm.llm_reasoning_effort,
            'summary': settings.llm.llm_reasoning_summary,
            'enabled': settings.llm.llm_reasoning_enabled,
            'exclude': False,
        }
    },
)
consultation_pdf_renderer = ConsultationPdfRenderer(settings.consultation)
smtp_client = SmtpClient(settings.email)
consultation_preparation_service = ConsultationPreparationService(
    llm_client=llm_client,
    pdf_renderer=consultation_pdf_renderer,
)
consultation_delivery_service = ConsultationDeliveryService(
    preparation_service=consultation_preparation_service,
    smtp_client=smtp_client,
)

health_registry = HealthRegistry()
health_registry.register('rag_service', rag_client.check_health)

mcp = FastMCP(
    'vera-tools',
    host=settings.app.mcp_service_host,
    port=settings.app.mcp_service_port,
    stateless_http=True,
)
register_all_tools(
    mcp,
    rag_client=rag_client,
    rag_top_k=settings.rag.rag_search_top_k,
    consultation_delivery_service=consultation_delivery_service,
)


def create_streamable_http_app() -> Starlette:
    """Создаёт MCP ASGI-app и закрывает HTTP-клиент на shutdown процесса.

    `FastMCP.streamable_http_app()` уже задаёт ASGI-lifespan менеджера
    streamable-http сессий. Оборачиваем именно его, сохраняя исходный
    lifecycle, вместо использования session-level `FastMCP(lifespan=...)`.
    """
    app = mcp.streamable_http_app()
    session_manager_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def process_lifespan(starlette_app: Starlette) -> AsyncIterator[None]:
        async with session_manager_lifespan(starlette_app):
            try:
                yield
            finally:
                await httpx_client.aclose()

    app.router.lifespan_context = process_lifespan
    return app


@mcp.custom_route('/health', methods=['GET'])
async def health(request: Request) -> JSONResponse:
    """Код ответа всегда `200` — недоступность зависимости отражается в
    теле, не в коде (MCP_SERVICE_PLAN.md, раздел 3.3). Никакого жёсткого
    startup-чека RAG Service нет нигде: сервис должен уметь стартовать и
    отвечать на `/health` даже если RAG временно недоступен — недоступность
    проявляется как ошибка конкретного вызова `vera_rag_kb`, не как
    невозможность поднять контейнер (раздел 4.2, тот же принцип, каким
    Agent Service обошёлся с отсутствующим MCP Tools Server)."""
    dependency_statuses = await health_registry.run()
    return JSONResponse({'status': 'ok', **dependency_statuses})


def run() -> None:
    # Вызывается здесь, не на уровне модуля — импорт `app.main` (например,
    # тестами) не должен иметь побочного эффекта в виде настройки глобального
    # OTel-провайдера на реальный OTLP-эндпоинт. Безопасно вызывать после
    # того, как `get_tracer()` уже был вызван в `app/tools/vera_rag_kb.py` и
    # `app/clients/rag_client.py` при их импорте — `trace.get_tracer()`
    # возвращает прокси, резолвящий актуальный провайдер в момент создания
    # span'а, а не в момент самого вызова `get_tracer()`.
    configure_tracing(settings.observability)
    logger.info('🚀 Старт vera_mcp_service')
    try:
        import uvicorn

        uvicorn.run(
            create_streamable_http_app(),
            host=mcp.settings.host,
            port=mcp.settings.port,
            log_level=mcp.settings.log_level.lower(),
        )
    finally:
        shutdown_tracing()


if __name__ == '__main__':
    run()

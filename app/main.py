import httpx
from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.clients.rag_client import RagClient
from app.core.config_logger import logger
from app.core.settings import get_settings
from app.health import HealthRegistry
from app.observability.tracing import configure_tracing
from app.tools import register_all_tools

settings = get_settings()

# Собирается синхронно на уровне модуля, не через `lifespan=` конструктора
# `FastMCP`. Найдено эмпирически: у `FastMCP` `lifespan` — это контекст
# низкоуровневого MCP-сервера, привязанный к жизненному циклу MCP-сессии
# (через `StreamableHTTPSessionManager`), а не ASGI-старт всего процесса,
# как `lifespan` в FastAPI. Тулы, зарегистрированные там, не гарантированно
# видны до первого реального MCP-запроса — подтверждено вручную: `GET
# /health` (обычный Starlette custom_route, не MCP-сессия) отдавался
# раньше, чем такой lifespan успевал выполниться. `httpx.AsyncClient()`
# не требует запущенного event loop для создания — конструктор синхронный,
# async нужен только для `.get()/.post()/.aclose()` — поэтому создание
# здесь безопасно.
httpx_client = httpx.AsyncClient()
rag_client = RagClient(httpx_client=httpx_client, settings=settings.rag)

health_registry = HealthRegistry()
health_registry.register('rag_service', rag_client.check_health)

mcp = FastMCP(
    'vera-tools',
    host=settings.app.mcp_service_host,
    port=settings.app.mcp_service_port,
    stateless_http=True,
)
register_all_tools(mcp, rag_client=rag_client, rag_top_k=settings.rag.rag_search_top_k)


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
    mcp.run(transport='streamable-http')


if __name__ == '__main__':
    run()

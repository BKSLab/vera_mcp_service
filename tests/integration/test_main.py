"""Сборка `app/main.py` — реальный сервер, реальные регистрации тулов и
health-чеков (MCP_SERVICE_PLAN.md, Этап 4).

`rag_service` в `/health` намеренно не проверяется на конкретное значение —
зависит от того, поднят ли `vera_rag_service` локально в момент прогона
тестов (в CI/по умолчанию не поднят, реальное значение — `unreachable`);
детерминированное покрытие `RagClient.check_health()` — в
`tests/unit/clients/test_rag_client.py`. Здесь проверяется только форма
ответа и то, что сервис не падает независимо от доступности RAG.

**Находка:** `app.main.mcp` — процессный синглтон (как и в реальном
деплое — `mcp.run()` вызывается ровно один раз за процесс), и
`FastMCP.streamable_http_app()` можно поднять только один раз за время
жизни инстанса (`StreamableHTTPSessionManager.run() can only be called
once per instance`). Обе проверки поэтому — один тест с одним запуском
сервера (`async with`, как в `test_protocol_compatibility.py`), не два
отдельных теста с общей fixture — module-scoped async fixture у
`pytest-asyncio` не совместим по умолчанию с function-scoped event loop
в этом проекте (`pytest.ini` не настраивает `asyncio_default_fixture_loop_scope`)
и подвешивает прогон между тестами.
"""

import asyncio
import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import uvicorn
from langchain_mcp_adapters.client import MultiServerMCPClient
from sse_starlette.sse import AppStatus

from app.main import mcp


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as temp_socket:
        temp_socket.bind(('127.0.0.1', 0))
        return temp_socket.getsockname()[1]


@asynccontextmanager
async def _run_app_main_server() -> AsyncIterator[str]:
    """Тот же обход `AppStatus.should_exit`, что и в
    `test_protocol_compatibility.py` (раздел 0.2). Вызывается ровно один
    раз за модуль — `app.main.mcp` синглтон, повторный запуск его
    `streamable_http_app()` в этом же процессе невозможен."""
    app = mcp.streamable_http_app()
    port = _free_port()
    config = uvicorn.Config(app, host='127.0.0.1', port=port, log_level='warning')
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve())
    try:
        while not server.started:
            await asyncio.sleep(0.02)
        yield f'http://127.0.0.1:{port}'
    finally:
        server.should_exit = True
        await server_task
        AppStatus.should_exit = False


async def test_health_and_kb_search_tool_on_real_server():
    async with _run_app_main_server() as base_url:
        async with httpx.AsyncClient(base_url=base_url) as http_client:
            health_response = await http_client.get('/health')

        assert health_response.status_code == 200
        body = health_response.json()
        assert body['status'] == 'ok'
        assert body['rag_service'] in {'ok', 'unreachable'}

        mcp_client = MultiServerMCPClient(
            {'vera-tools': {'url': f'{base_url}/mcp', 'transport': 'streamable_http', 'timeout': 5.0}},
            handle_tool_errors=False,
        )
        tools = await mcp_client.get_tools()

        assert {tool.name for tool in tools} == {'vera_rag_kb'}

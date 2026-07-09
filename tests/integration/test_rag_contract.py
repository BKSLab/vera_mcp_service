"""Contract-тест: `RagClient` против настоящего HTTP-стаба, реализующего
схему `POST /api/v1/search` из `vera_rag_service` (MCP_SERVICE_PLAN.md,
Этап 6.3).

Отличие от `tests/unit/clients/test_rag_client.py` (Этап 1): там
`httpx.MockTransport` подменяет транспорт, здесь — настоящий сетевой
запрос к настоящему (пусть и не production) HTTP-серверу, поднятому
`uvicorn`. Проверяет то, что подмена транспорта не может: реальную
сериализацию заголовков/тела через сокет.

**Известное ограничение (см. также раздел 4, риски):** стаб написан вручную
и не синхронизирован автоматически со схемой `vera_rag_service` — реальное
расхождение контракта обнаружится не раньше Этапа 9 (сквозной E2E), не здесь.
"""

import asyncio
import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import pytest
import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from app.clients.rag_client import RagClient
from app.core.settings import RagClientSettings
from app.exceptions.rag import RagUnavailableError

STUB_API_KEY = 'stub-api-key'


def _stub_rag_app(chunks: list[dict] | None = None) -> Starlette:
    async def search(request: Request) -> JSONResponse:
        if request.headers.get('x-api-key') != STUB_API_KEY:
            return JSONResponse({'detail': 'invalid api key'}, status_code=401)

        body = await request.json()
        assert set(body) == {'query', 'audience', 'top_k'}, f'Неожиданное тело запроса: {body!r}'

        return JSONResponse({'chunks': chunks or []})

    return Starlette(routes=[Route('/api/v1/search', search, methods=['POST'])])


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as temp_socket:
        temp_socket.bind(('127.0.0.1', 0))
        return temp_socket.getsockname()[1]


@asynccontextmanager
async def _run_stub_server(app: Starlette) -> AsyncIterator[str]:
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


def _settings(base_url: str) -> RagClientSettings:
    return RagClientSettings(
        rag_service_url=base_url,
        rag_service_api_key=STUB_API_KEY,
        rag_search_timeout_seconds=5.0,
        rag_search_top_k=5,
    )


async def test_rag_client_search_against_real_http_stub_server():
    app = _stub_rag_app(chunks=[{'chunk_id': 'c1', 'text': 'квота 2%'}])
    async with _run_stub_server(app) as base_url, httpx.AsyncClient() as httpx_client:
        client = RagClient(httpx_client=httpx_client, settings=_settings(base_url))

        result = await client.search(query='квота', audience='both', top_k=5)

    assert result == {'chunks': [{'chunk_id': 'c1', 'text': 'квота 2%'}]}


async def test_rag_client_search_rejects_wrong_api_key_as_unavailable():
    app = _stub_rag_app()
    async with _run_stub_server(app) as base_url, httpx.AsyncClient() as httpx_client:
        settings = RagClientSettings(
            rag_service_url=base_url,
            rag_service_api_key='wrong-key',
            rag_search_timeout_seconds=5.0,
            rag_search_top_k=5,
        )
        client = RagClient(httpx_client=httpx_client, settings=settings)

        with pytest.raises(RagUnavailableError):
            await client.search(query='квота', audience='both', top_k=5)

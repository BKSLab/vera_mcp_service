import json

import httpx
import pytest

from app.clients.rag_client import RagClient
from app.core.settings import RagClientSettings
from app.exceptions.rag import RagUnavailableError


def _settings() -> RagClientSettings:
    return RagClientSettings(
        rag_service_url='http://rag.test',
        rag_service_api_key='test-api-key',
        rag_search_timeout_seconds=5.0,
        rag_search_top_k=5,
    )


def _client(handler) -> RagClient:
    httpx_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return RagClient(httpx_client=httpx_client, settings=_settings())


async def test_search_returns_chunks_on_success():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={'chunks': [{'chunk_id': 'c1', 'text': 'квота 2%'}]})

    client = _client(handler)

    result = await client.search(query='квота', audience='both', top_k=5)

    assert result == {'chunks': [{'chunk_id': 'c1', 'text': 'квота 2%'}]}


async def test_search_returns_empty_chunks_as_valid_result_not_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={'chunks': []})

    client = _client(handler)

    result = await client.search(query='непонятный вопрос', audience='both', top_k=5)

    assert result == {'chunks': []}


async def test_search_sends_api_key_header_and_request_body():
    captured_request: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured_request['headers'] = request.headers
        captured_request['body'] = request.content
        captured_request['url'] = str(request.url)
        return httpx.Response(200, json={'chunks': []})

    client = _client(handler)

    await client.search(query='квота', audience='employer', top_k=3)

    assert captured_request['headers']['x-api-key'] == 'test-api-key'
    assert captured_request['url'] == 'http://rag.test/api/v1/search'
    assert json.loads(captured_request['body']) == {'query': 'квота', 'audience': 'employer', 'top_k': 3}


async def test_search_raises_rag_unavailable_on_timeout():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException('timed out', request=request)

    client = _client(handler)

    with pytest.raises(RagUnavailableError):
        await client.search(query='квота', audience='both', top_k=5)


async def test_search_raises_rag_unavailable_on_connect_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError('connection refused', request=request)

    client = _client(handler)

    with pytest.raises(RagUnavailableError):
        await client.search(query='квота', audience='both', top_k=5)


async def test_search_raises_rag_unavailable_on_500():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={'detail': 'embedding API unavailable'})

    client = _client(handler)

    with pytest.raises(RagUnavailableError):
        await client.search(query='квота', audience='both', top_k=5)


async def test_search_raises_rag_unavailable_on_429():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={'detail': 'rate limit exceeded'})

    client = _client(handler)

    with pytest.raises(RagUnavailableError):
        await client.search(query='квота', audience='both', top_k=5)


async def test_search_raises_rag_unavailable_on_invalid_json():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b'not json')

    client = _client(handler)

    with pytest.raises(RagUnavailableError):
        await client.search(query='квота', audience='both', top_k=5)


async def test_search_raises_rag_unavailable_on_missing_chunks_field():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={'unexpected': 'shape'})

    client = _client(handler)

    with pytest.raises(RagUnavailableError):
        await client.search(query='квота', audience='both', top_k=5)


async def test_check_health_returns_true_on_200():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={'status': 'ok', 'database': 'ok'})

    client = _client(handler)

    assert await client.check_health() is True


async def test_check_health_returns_false_on_503():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={'detail': 'База данных недоступна.'})

    client = _client(handler)

    assert await client.check_health() is False


async def test_check_health_returns_false_on_connection_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError('connection refused', request=request)

    client = _client(handler)

    assert await client.check_health() is False


async def test_check_health_requests_expected_path():
    captured_request: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured_request['url'] = str(request.url)
        return httpx.Response(200, json={'status': 'ok'})

    client = _client(handler)

    await client.check_health()

    assert captured_request['url'] == 'http://rag.test/api/v1/health'

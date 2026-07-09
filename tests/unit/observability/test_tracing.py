import httpx
import pytest
from mcp.server.fastmcp import FastMCP
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.clients.rag_client import RagClient
from app.core.settings import RagClientSettings
from app.observability.tracing import reset_for_tests
from app.tools.kb_search import register_kb_search

# `set_tracer_provider()` можно успешно вызвать только один раз за процесс
# (см. docstring `reset_for_tests`) — настраиваем провайдер один раз на
# модуль, между тестами только чистим накопленные spans (та же находка,
# что уже задокументирована в vera_agent_service).
_exporter = InMemorySpanExporter()
reset_for_tests(_exporter)


@pytest.fixture(autouse=True)
def _clear_spans():
    _exporter.clear()
    yield


def _settings() -> RagClientSettings:
    return RagClientSettings(
        rag_service_url='http://rag.test',
        rag_service_api_key='test-api-key',
        rag_search_timeout_seconds=5.0,
        rag_search_top_k=5,
    )


def _rag_client(chunks: list[dict] | None = None) -> RagClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={'chunks': chunks or []})

    httpx_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return RagClient(httpx_client=httpx_client, settings=_settings())


def _span_names() -> list[str]:
    return [span.name for span in _exporter.get_finished_spans()]


async def test_rag_search_creates_named_span():
    client = _rag_client()

    await client.search(query='квота', audience='both', top_k=5)

    assert 'rag.search' in _span_names()


async def test_kb_search_tool_call_creates_span_with_tool_name_attribute():
    mcp = FastMCP('test-tracing')
    register_kb_search(mcp, _rag_client(), top_k=5)

    await mcp.call_tool('kb_search', {'query': 'квота'})

    tool_call_spans = [span for span in _exporter.get_finished_spans() if span.name == 'mcp.tool_call']
    assert len(tool_call_spans) == 1
    assert tool_call_spans[0].attributes['mcp.tool_name'] == 'kb_search'


async def test_kb_search_span_tree_matches_architecture_doc():
    """Дерево должно совпасть с примером в `AGENT_VERA_ARCHITECTURE.md`,
    раздел "Observability": `[span] mcp.tool_call: kb_search └── [span] rag.search`."""
    mcp = FastMCP('test-tracing')
    register_kb_search(mcp, _rag_client(), top_k=5)

    await mcp.call_tool('kb_search', {'query': 'квота'})

    spans = {span.name: span for span in _exporter.get_finished_spans()}
    assert set(spans) == {'mcp.tool_call', 'rag.search'}
    tool_call_span = spans['mcp.tool_call']
    rag_search_span = spans['rag.search']
    assert rag_search_span.parent.span_id == tool_call_span.context.span_id

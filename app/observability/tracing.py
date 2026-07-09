from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter

from app.core.settings import ObservabilitySettings

SERVICE_NAME: str = 'vera_mcp_service'

_provider: TracerProvider | None = None


def configure_tracing(settings: ObservabilitySettings) -> TracerProvider:
    """Инициализирует OpenTelemetry → Arize Phoenix (MCP_SERVICE_PLAN.md, Этап 5).

    В отличие от Agent Service здесь нет автоинструментации — `mcp`/`FastMCP`
    ею не покрываются (`AGENT_VERA_ARCHITECTURE.md`, раздел "Observability") —
    только ручные spans на границах: `mcp.tool_call` (`app/tools/kb_search.py`)
    и вложенный `rag.search` (`app/clients/rag_client.py`).

    Идемпотентна — повторный вызов возвращает уже созданный `TracerProvider`,
    не плодит дублирующиеся процессоры.
    """
    global _provider
    if _provider is not None:
        return _provider

    provider = TracerProvider(resource=Resource.create({'service.name': SERVICE_NAME}))
    exporter = OTLPSpanExporter(endpoint=settings.phoenix_otlp_endpoint)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    _provider = provider
    return provider


def get_tracer() -> trace.Tracer:
    """Трейсер для ручных spans. Безопасен для вызова до `configure_tracing()`
    (например в юнит-тестах, не поднимающих Phoenix) — без настроенного
    провайдера OpenTelemetry отдаёт no-op трейсер, `start_as_current_span`
    просто ничего не делает."""
    return trace.get_tracer(SERVICE_NAME)


def reset_for_tests(exporter: SpanExporter | None = None) -> TracerProvider:
    """Только для тестов. Настраивает провайдер с указанным экспортёром
    (например `InMemorySpanExporter`), чтобы проверить фактически
    созданные spans без реального Phoenix.

    **Вызывать один раз за тестовый процесс** (например на уровне модуля
    теста), не в каждом тесте: `opentelemetry.trace.set_tracer_provider()`
    можно успешно вызвать только один раз за процесс — повторные вызовы
    молча игнорируются самим OpenTelemetry SDK (та же находка, что уже
    задокументирована в `vera_agent_service/app/observability/tracing.py`).
    Между тестами достаточно `exporter.clear()`.
    """
    global _provider
    _provider = None
    provider = TracerProvider(resource=Resource.create({'service.name': SERVICE_NAME}))
    if exporter is not None:
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor

        provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    _provider = provider
    return provider

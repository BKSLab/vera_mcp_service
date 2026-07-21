import logging
from collections.abc import Mapping

from opentelemetry import propagate, trace
from opentelemetry.context import Context
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter

from app.core.settings import ObservabilitySettings

SERVICE_NAME: str = 'vera_mcp_service'
logger = logging.getLogger(SERVICE_NAME)

_provider: TracerProvider | None = None
_shutdown = False


def configure_tracing(settings: ObservabilitySettings) -> TracerProvider:
    """Инициализирует OpenTelemetry → Arize Phoenix (MCP_SERVICE_PLAN.md, Этап 5).

    В отличие от Agent Service здесь нет автоинструментации — `mcp`/`FastMCP`
    ею не покрываются (`AGENT_VERA_ARCHITECTURE.md`, раздел "Observability") —
    один ручной span `mcp.execute.<tool>` на серверной границе. Фактический
    `rag.search` принадлежит RAG Service и приходит по W3C trace context.

    Идемпотентна — повторный вызов возвращает уже созданный `TracerProvider`,
    не плодит дублирующиеся процессоры.
    """
    global _provider, _shutdown
    if _provider is not None:
        return _provider

    provider = TracerProvider(resource=Resource.create({'service.name': SERVICE_NAME}))
    _add_exporter(provider, settings)
    trace.set_tracer_provider(provider)

    _provider = provider
    _shutdown = False
    return provider


def _create_otlp_exporter(settings: ObservabilitySettings) -> OTLPSpanExporter:
    return OTLPSpanExporter(
        endpoint=settings.phoenix_otlp_endpoint,
        headers={'x-project-name': settings.phoenix_project_name},
    )


def _add_exporter(provider: TracerProvider, settings: ObservabilitySettings) -> None:
    if settings.phoenix_enabled:
        provider.add_span_processor(BatchSpanProcessor(_create_otlp_exporter(settings)))


def get_tracer() -> trace.Tracer:
    """Трейсер для ручных spans. Безопасен для вызова до `configure_tracing()`
    (например в юнит-тестах, не поднимающих Phoenix) — без настроенного
    провайдера OpenTelemetry отдаёт no-op трейсер, `start_as_current_span`
    просто ничего не делает."""
    return trace.get_tracer(SERVICE_NAME)


def extract_trace_context(headers: Mapping[str, str] | None) -> Context | None:
    """Извлекает W3C-контекст; прямой unit-вызов без HTTP остаётся валидным root."""
    if headers is None:
        return None
    return propagate.extract(headers)


def force_flush_tracing(timeout_millis: int = 10_000) -> bool:
    if _provider is None or _shutdown:
        return True
    try:
        return _provider.force_flush(timeout_millis=timeout_millis)
    except Exception:  # noqa: BLE001 - телеметрия не должна ломать shutdown
        logger.exception('Не удалось выполнить force_flush OpenTelemetry')
        return False


def shutdown_tracing(timeout_millis: int = 10_000) -> None:
    global _shutdown
    if _provider is None or _shutdown:
        return
    force_flush_tracing(timeout_millis=timeout_millis)
    try:
        _provider.shutdown()
    except Exception:  # noqa: BLE001 - телеметрия не должна ломать shutdown
        logger.exception('Не удалось завершить OpenTelemetry provider')
    finally:
        _shutdown = True


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
    global _provider, _shutdown
    _provider = None
    provider = TracerProvider(resource=Resource.create({'service.name': SERVICE_NAME}))
    if exporter is not None:
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor

        provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    _provider = provider
    _shutdown = False
    return provider

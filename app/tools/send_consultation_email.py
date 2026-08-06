from mcp.server.fastmcp import Context, FastMCP
from opentelemetry.trace import Status, StatusCode

from app.observability.tracing import extract_trace_context, get_tracer
from app.services.consultation_delivery import ConsultationDeliveryService

tracer = get_tracer()

SEND_CONSULTATION_EMAIL_DESCRIPTION = (
    'Формирует PDF из уже подготовленного итогового текста консультации '
    'Ассистента Веры '
    'и отправляет документ на подтверждённый пользователем email. Вызывай '
    'инструмент только после явной просьбы или подтверждения пользователя. '
    'consultation_text — полный итоговый текст консультации; агенту не нужно '
    'самостоятельно разбивать его на разделы или добавлять форматирование. '
    'consultation_topic — краткая тема консультации на русском языке без слова '
    '«Консультация», даты и расширения файла; сервис сам оформит заголовок и '
    'имя PDF. '
    'email — адрес, который пользователь сообщил или явно подтвердил. '
    'Инструмент сам структурирует текст, формирует доступный PDF и отправляет '
    'письмо. status="error" означает, что отправка не была подтверждена. '
    'Не повторяй вызов автоматически после таймаута: письмо могло быть принято '
    'SMTP-сервером до разрыва соединения.'
)


def register_send_consultation_email(
    mcp: FastMCP,
    consultation_delivery_service: ConsultationDeliveryService,
) -> None:
    """Регистрирует мутирующий MCP-инструмент отправки консультации."""

    async def send_consultation_email(
        consultation_text: str,
        consultation_topic: str,
        email: str,
        ctx: Context | None = None,
    ) -> dict:
        try:
            request_context = ctx.request_context if ctx is not None else None
        except (AttributeError, ValueError):
            request_context = None
        request = getattr(request_context, 'request', None)
        parent_context = extract_trace_context(getattr(request, 'headers', None))

        with tracer.start_as_current_span(
            'mcp.execute.send_consultation_email',
            context=parent_context,
            attributes={
                'openinference.span.kind': 'TOOL',
                'mcp.server.name': 'vera-tools',
                'mcp.tool.name': 'send_consultation_email',
                'consultation.input_length': len(consultation_text),
                'consultation.topic_length': len(consultation_topic),
            },
        ) as span:
            try:
                result = await consultation_delivery_service.send(
                    consultation_text=consultation_text,
                    consultation_topic=consultation_topic,
                    email=email,
                )
            except Exception as error:
                span.set_attribute('consultation.outcome', 'unexpected_error')
                span.record_exception(error)
                span.set_status(Status(StatusCode.ERROR, type(error).__name__))
                raise

            payload = result.model_dump(mode='json')
            span.set_attribute(
                'consultation.outcome',
                payload.get('code', payload['status']),
            )
            return payload

    mcp.add_tool(
        send_consultation_email,
        name='send_consultation_email',
        description=SEND_CONSULTATION_EMAIL_DESCRIPTION,
    )

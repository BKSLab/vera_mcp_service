import logging

from app.clients.llm import LlmClient
from app.exceptions.consultation import ConsultationFormattingError
from app.exceptions.llm import LlmApiRequestError
from app.observability.tracing import get_tracer
from app.renderers.consultation_pdf import ConsultationPdfRenderer
from app.schemas.consultation import (
    GeneratedConsultationDocument,
    PreparedConsultation,
)
from app.services.prompts.consultation_formatting import (
    CONSULTATION_FORMATTING_PROMPT,
)

logger = logging.getLogger(__name__)
tracer = get_tracer()


class ConsultationPreparationService:
    """Структурирует исходный текст и передаёт результат PDF-рендереру."""

    def __init__(
        self,
        *,
        llm_client: LlmClient,
        pdf_renderer: ConsultationPdfRenderer,
    ):
        self._llm_client = llm_client
        self._pdf_renderer = pdf_renderer

    async def prepare(
        self,
        consultation_text: str,
    ) -> GeneratedConsultationDocument:
        with tracer.start_as_current_span('consultation.format') as span:
            try:
                prepared = await self._llm_client.get_llm_response(
                    content=(
                        '<INPUT_DATA>\n'
                        f'{consultation_text}\n'
                        '</INPUT_DATA>'
                    ),
                    prompt=CONSULTATION_FORMATTING_PROMPT,
                    schema=PreparedConsultation,
                )
            except LlmApiRequestError as error:
                span.set_attribute('consultation.outcome', 'error')
                raise ConsultationFormattingError('llm_attempts_exhausted') from error

            if not isinstance(prepared, PreparedConsultation):
                span.set_attribute('consultation.outcome', 'error')
                raise ConsultationFormattingError('unexpected_llm_result_type')

            span.set_attribute('consultation.outcome', 'ok')
            span.set_attribute('consultation.section_count', len(prepared.sections))

        return await self._pdf_renderer.render(prepared)

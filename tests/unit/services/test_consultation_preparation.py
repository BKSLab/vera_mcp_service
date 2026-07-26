from unittest.mock import AsyncMock

import pytest

from app.clients.llm import LlmClient
from app.exceptions.consultation import ConsultationFormattingError
from app.exceptions.llm import LlmApiRequestError
from app.renderers.consultation_pdf import ConsultationPdfRenderer
from app.schemas.consultation import (
    GeneratedConsultationDocument,
    PreparedConsultation,
)
from app.services.consultation_preparation import ConsultationPreparationService


def _prepared() -> PreparedConsultation:
    return PreparedConsultation(
        title='Заголовок',
        intro=['Вступление.'],
        sections=[],
        conclusion=[],
        sources=[],
    )


def _service() -> tuple[ConsultationPreparationService, AsyncMock, AsyncMock]:
    llm = AsyncMock(spec=LlmClient)
    llm.get_llm_response.return_value = _prepared()
    renderer = AsyncMock(spec=ConsultationPdfRenderer)
    renderer.render.return_value = GeneratedConsultationDocument(
        filename='consultation.pdf',
        content=b'%PDF-test',
    )
    return (
        ConsultationPreparationService(
            llm_client=llm,
            pdf_renderer=renderer,
        ),
        llm,
        renderer,
    )


async def test_preparation_passes_input_as_data_and_renders_validated_schema():
    service, llm, renderer = _service()

    result = await service.prepare('Исходный текст.')

    assert result.filename == 'consultation.pdf'
    call = llm.get_llm_response.await_args
    assert call.kwargs['content'] == '<INPUT_DATA>\nИсходный текст.\n</INPUT_DATA>'
    assert call.kwargs['schema'] is PreparedConsultation
    assert 'max_completion_tokens' not in call.kwargs
    renderer.render.assert_awaited_once_with(_prepared())


async def test_preparation_maps_llm_final_error_and_skips_renderer():
    service, llm, renderer = _service()
    llm.get_llm_response.side_effect = LlmApiRequestError(
        error_details='timeout',
        request_url='https://llm.test/chat/completions',
    )

    with pytest.raises(ConsultationFormattingError):
        await service.prepare('Исходный текст.')

    renderer.render.assert_not_awaited()

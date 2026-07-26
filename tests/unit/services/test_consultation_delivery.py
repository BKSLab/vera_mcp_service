from unittest.mock import AsyncMock

import pytest

from app.clients.smtp_client import SmtpClient
from app.exceptions.consultation import (
    ConsultationEmailDeliveryError,
    ConsultationFormattingError,
    ConsultationPdfGenerationError,
)
from app.schemas.consultation import GeneratedConsultationDocument
from app.services.consultation_delivery import ConsultationDeliveryService
from app.services.consultation_preparation import ConsultationPreparationService


def _document() -> GeneratedConsultationDocument:
    return GeneratedConsultationDocument(
        filename='konsultatsiya-vera-test.pdf',
        content=b'%PDF-test',
    )


def _service() -> tuple[
    ConsultationDeliveryService,
    AsyncMock,
    AsyncMock,
]:
    preparation = AsyncMock(spec=ConsultationPreparationService)
    preparation.prepare.return_value = _document()
    smtp = AsyncMock(spec=SmtpClient)
    smtp.send_document.return_value = 1
    service = ConsultationDeliveryService(
        preparation_service=preparation,
        smtp_client=smtp,
    )
    return service, preparation, smtp


@pytest.mark.parametrize(
    'email',
    [
        '',
        'not-an-email',
        'user@example.com\r\nBcc: attacker@example.com',
    ],
)
async def test_invalid_email_returns_business_error_without_side_effects(email):
    service, preparation, smtp = _service()

    result = await service.send(
        consultation_text='Полный текст консультации.',
        email=email,
    )

    assert result.model_dump(mode='json') == {
        'status': 'error',
        'code': 'invalid_email',
        'message': 'Указан некорректный адрес электронной почты.',
    }
    preparation.prepare.assert_not_awaited()
    smtp.send_document.assert_not_awaited()


async def test_empty_text_returns_business_error():
    service, preparation, smtp = _service()

    result = await service.send(consultation_text='   ', email='user@example.com')

    assert result.code == 'invalid_consultation_text'
    preparation.prepare.assert_not_awaited()
    smtp.send_document.assert_not_awaited()


async def test_long_real_consultation_is_not_rejected_or_truncated():
    service, preparation, smtp = _service()
    consultation_text = 'Большой содержательный текст. ' * 10_000

    result = await service.send(
        consultation_text=consultation_text,
        email='user@example.com',
    )

    assert result.status == 'ok'
    preparation.prepare.assert_awaited_once_with(consultation_text.strip())
    smtp.send_document.assert_awaited_once()


@pytest.mark.parametrize(
    ('error', 'expected_code'),
    [
        (
            ConsultationFormattingError('failed'),
            'consultation_formatting_failed',
        ),
        (
            ConsultationPdfGenerationError('failed'),
            'pdf_generation_failed',
        ),
    ],
)
async def test_preparation_errors_are_mapped_and_smtp_is_not_called(
    error,
    expected_code,
):
    service, preparation, smtp = _service()
    preparation.prepare.side_effect = error

    result = await service.send(
        consultation_text='Текст.',
        email='user@example.com',
    )

    assert result.code == expected_code
    smtp.send_document.assert_not_awaited()


async def test_smtp_error_is_mapped_to_business_error():
    service, preparation, smtp = _service()
    smtp.send_document.side_effect = ConsultationEmailDeliveryError(
        error_category='network',
        attempts=3,
    )

    result = await service.send(
        consultation_text='Текст.',
        email='user@example.com',
    )

    assert result.code == 'email_delivery_failed'
    preparation.prepare.assert_awaited_once()


async def test_success_returns_normalized_email_and_document_name():
    service, preparation, smtp = _service()

    result = await service.send(
        consultation_text=' Текст консультации. ',
        email=' User@EXAMPLE.COM ',
    )

    assert result.model_dump(mode='json') == {
        'status': 'ok',
        'email': 'User@example.com',
        'document_name': 'konsultatsiya-vera-test.pdf',
        'message': 'Консультация успешно отправлена.',
    }
    preparation.prepare.assert_awaited_once_with('Текст консультации.')
    smtp.send_document.assert_awaited_once_with(
        recipient='User@example.com',
        document=_document(),
    )

import logging

from pydantic import EmailStr, TypeAdapter, ValidationError

from app.clients.smtp_client import SmtpClient
from app.exceptions.consultation import (
    ConsultationEmailDeliveryError,
    ConsultationFormattingError,
    ConsultationPdfGenerationError,
)
from app.schemas.consultation import (
    ConsultationSendError,
    ConsultationSendResult,
    ConsultationSendSuccess,
    ConsultationTopic,
)
from app.services.consultation_preparation import ConsultationPreparationService

logger = logging.getLogger(__name__)
_EMAIL_ADAPTER = TypeAdapter(EmailStr)
_TOPIC_ADAPTER = TypeAdapter(ConsultationTopic)

ERROR_MESSAGES = {
    'invalid_email': 'Указан некорректный адрес электронной почты.',
    'invalid_consultation_text': (
        'Не удалось подготовить консультацию: текст отсутствует.'
    ),
    'invalid_consultation_topic': (
        'Не удалось подготовить консультацию: укажите краткую тему.'
    ),
    'consultation_formatting_failed': (
        'Не удалось подготовить текст консультации. Попробуйте позже.'
    ),
    'pdf_generation_failed': (
        'Не удалось сформировать документ консультации. Попробуйте позже.'
    ),
    'email_delivery_failed': (
        'Не удалось отправить консультацию по электронной почте. Попробуйте позже.'
    ),
}


class ConsultationDeliveryService:
    """Последовательный бизнес-процесс от входной валидации до SMTP."""

    def __init__(
        self,
        *,
        preparation_service: ConsultationPreparationService,
        smtp_client: SmtpClient,
    ):
        self._preparation_service = preparation_service
        self._smtp_client = smtp_client

    async def send(
        self,
        *,
        consultation_text: str,
        consultation_topic: str,
        email: str,
    ) -> ConsultationSendResult:
        normalized_email = self._validate_email(email)
        if normalized_email is None:
            return self._error('invalid_email')

        normalized_text = consultation_text.strip()
        if not normalized_text:
            return self._error('invalid_consultation_text')

        normalized_topic = self._validate_topic(consultation_topic)
        if normalized_topic is None:
            return self._error('invalid_consultation_topic')

        logger.info(
            '📄 Подготовка консультации: input_length=%d',
            len(normalized_text),
        )
        try:
            document = await self._preparation_service.prepare(
                normalized_text,
                normalized_topic,
            )
        except ConsultationFormattingError:
            logger.warning('⚠️ Не удалось структурировать консультацию')
            return self._error('consultation_formatting_failed')
        except ConsultationPdfGenerationError:
            logger.warning('⚠️ Не удалось сформировать PDF консультации')
            return self._error('pdf_generation_failed')

        try:
            await self._smtp_client.send_document(
                recipient=normalized_email,
                document=document,
            )
        except ConsultationEmailDeliveryError:
            logger.warning(
                '⚠️ SMTP не подтвердил отправку документа %s',
                document.filename,
            )
            return self._error('email_delivery_failed')

        logger.info(
            '✅ Консультация отправлена: document=%s size_bytes=%d',
            document.filename,
            document.size_bytes,
        )
        return ConsultationSendSuccess(
            email=normalized_email,
            document_name=document.filename,
        )

    def _validate_email(self, value: str) -> str | None:
        if not isinstance(value, str):
            return None
        candidate = value.strip()
        if (
            not candidate
            or '\r' in candidate
            or '\n' in candidate
        ):
            return None
        try:
            return str(_EMAIL_ADAPTER.validate_python(candidate))
        except ValidationError:
            return None

    def _validate_topic(self, value: str) -> str | None:
        if not isinstance(value, str):
            return None
        candidate = ' '.join(value.split())
        try:
            return _TOPIC_ADAPTER.validate_python(candidate)
        except ValidationError:
            return None

    @staticmethod
    def _error(code: str) -> ConsultationSendError:
        return ConsultationSendError(code=code, message=ERROR_MESSAGES[code])

import asyncio
import logging
import random
import ssl
from datetime import UTC, datetime
from email.headerregistry import Address
from email.message import EmailMessage
from email.utils import format_datetime, make_msgid
from html import escape

import aiosmtplib
from aiosmtplib.errors import (
    SMTPAuthenticationError,
    SMTPException,
    SMTPRecipientsRefused,
    SMTPResponseException,
    SMTPServerDisconnected,
    SMTPTimeoutError,
)

from app.core.settings import EmailSettings
from app.exceptions.consultation import ConsultationEmailDeliveryError
from app.observability.tracing import get_tracer
from app.schemas.consultation import GeneratedConsultationDocument

logger = logging.getLogger(__name__)
tracer = get_tracer()


class SmtpClient:
    """Отправляет готовый PDF и централизует ограниченные SMTP-повторы."""

    def __init__(self, settings: EmailSettings):
        self._settings = settings

    def build_message(
        self,
        *,
        recipient: str,
        document: GeneratedConsultationDocument,
        message_id: str | None = None,
    ) -> EmailMessage:
        """Создаёт multipart/alternative + PDF без полного текста консультации."""
        from_email = str(self._settings.email)
        message = EmailMessage()
        message['From'] = Address(
            display_name=self._settings.consultation_email_from_name,
            addr_spec=from_email,
        )
        message['To'] = Address(addr_spec=recipient)
        message['Subject'] = self._settings.consultation_email_subject
        message['Date'] = format_datetime(datetime.now(UTC))
        message['Message-ID'] = message_id or make_msgid(
            domain=from_email.rsplit('@', maxsplit=1)[-1]
        )

        plain_body = (
            'Здравствуйте!\n\n'
            'Ваша консультация от Ассистента Веры подготовлена и приложена '
            'к этому письму в формате PDF.\n\n'
            'Работа для всех'
        )
        message.set_content(plain_body)

        safe_filename = escape(document.filename)
        message.add_alternative(
            f"""
<!DOCTYPE html>
<html lang="ru">
<body style="margin:0;padding:24px;background:#0a0a0a;color:#f0f0f0;font-family:Arial,sans-serif;">
  <main style="max-width:560px;margin:0 auto;padding:28px;border:1px solid #302800;border-top:3px solid #f5b800;border-radius:12px;background:#111111;">
    <p style="margin:0 0 8px;color:#f5b800;font-size:12px;font-weight:700;letter-spacing:2px;text-transform:uppercase;">Работа для всех</p>
    <h1 style="margin:0 0 18px;font-size:25px;line-height:1.25;">Ваша консультация готова</h1>
    <p style="margin:0 0 22px;color:#c8c8c8;line-height:1.65;">
      Консультация от Ассистента Веры приложена к письму в формате PDF.
    </p>
    <p style="margin:0;padding:14px 16px;border:1px solid #303030;border-radius:8px;background:#181818;color:#f0f0f0;">
      Файл: <strong style="color:#f5b800;">{safe_filename}</strong>
    </p>
  </main>
</body>
</html>
""".strip(),
            subtype='html',
        )
        message.add_attachment(
            document.content,
            maintype='application',
            subtype='pdf',
            filename=document.filename,
        )
        return message

    async def send_document(
        self,
        *,
        recipient: str,
        document: GeneratedConsultationDocument,
    ) -> int:
        """Возвращает номер успешной попытки или финальное доменное исключение."""
        message = self.build_message(recipient=recipient, document=document)
        last_category = 'unknown'

        with tracer.start_as_current_span('consultation.email.send') as span:
            span.set_attribute('consultation.pdf.size_bytes', document.size_bytes)
            for attempt in range(1, self._settings.smtp_max_attempts + 1):
                try:
                    await self._send_once(message)
                except Exception as error:
                    retryable, category = self._classify_error(error)
                    last_category = category
                    logger.warning(
                        '⚠️ SMTP attempt=%d/%d category=%s retryable=%s',
                        attempt,
                        self._settings.smtp_max_attempts,
                        category,
                        retryable,
                    )
                    if not retryable or attempt >= self._settings.smtp_max_attempts:
                        span.set_attribute('consultation.email.attempt_count', attempt)
                        span.set_attribute('consultation.outcome', 'error')
                        raise ConsultationEmailDeliveryError(
                            error_category=category,
                            attempts=attempt,
                        ) from error
                    await asyncio.sleep(self._get_backoff_delay(attempt))
                    continue

                span.set_attribute('consultation.email.attempt_count', attempt)
                span.set_attribute('consultation.outcome', 'ok')
                logger.info('✅ Письмо с консультацией отправлено: attempt=%d', attempt)
                return attempt

        raise ConsultationEmailDeliveryError(
            error_category=last_category,
            attempts=self._settings.smtp_max_attempts,
        )

    async def _send_once(self, message: EmailMessage) -> None:
        smtp = aiosmtplib.SMTP(
            hostname=self._settings.host_name,
            port=self._settings.port,
            use_tls=self._settings.smtp_use_tls,
            start_tls=self._settings.smtp_start_tls,
            validate_certs=self._settings.smtp_validate_certs,
            timeout=self._settings.smtp_timeout_seconds,
        )
        accepted = False
        try:
            await smtp.connect()
            await smtp.login(
                str(self._settings.email),
                self._settings.application_key.get_secret_value(),
            )
            await smtp.send_message(
                message,
                timeout=self._settings.smtp_timeout_seconds,
            )
            accepted = True
        finally:
            if accepted:
                # Ошибка QUIT после успешного DATA не должна инициировать повтор
                # и потенциальный дубликат уже принятого письма.
                try:
                    await smtp.quit(timeout=self._settings.smtp_timeout_seconds)
                except Exception:
                    smtp.close()
            else:
                smtp.close()

    def _get_backoff_delay(self, attempt: int) -> float:
        base_delay = min(
            self._settings.smtp_retry_max_delay_seconds,
            self._settings.smtp_retry_base_delay_seconds * (2 ** (attempt - 1)),
        )
        return base_delay + base_delay * 0.1 * random.random()

    @staticmethod
    def _classify_error(error: Exception) -> tuple[bool, str]:
        if isinstance(error, SMTPAuthenticationError):
            return False, 'authentication'
        if isinstance(error, SMTPRecipientsRefused):
            response_codes = [
                int(getattr(response, 'code', 0))
                for response in error.recipients
            ]
            retryable = bool(response_codes) and all(
                400 <= code < 500 for code in response_codes
            )
            return retryable, 'recipient_transient' if retryable else 'recipient_rejected'
        if isinstance(error, SMTPResponseException):
            code = int(error.code)
            if 400 <= code < 500:
                return True, 'smtp_4xx'
            return False, 'smtp_5xx' if code >= 500 else 'smtp_response'
        if isinstance(
            error,
            (
                SMTPTimeoutError,
                SMTPServerDisconnected,
                ConnectionError,
                TimeoutError,
                ssl.SSLError,
                OSError,
            ),
        ):
            return True, 'network'
        if isinstance(error, SMTPException):
            return False, 'smtp_protocol'
        if isinstance(error, ValueError):
            return False, 'message_or_configuration'
        return False, 'unexpected'

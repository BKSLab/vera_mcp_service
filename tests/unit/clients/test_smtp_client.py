from email.message import EmailMessage

import pytest
from aiosmtplib.errors import (
    SMTPAuthenticationError,
    SMTPRecipientRefused,
    SMTPRecipientsRefused,
    SMTPResponseException,
)

from app.clients import smtp_client as smtp_client_module
from app.clients.smtp_client import SmtpClient
from app.core.settings import EmailSettings
from app.exceptions.consultation import ConsultationEmailDeliveryError
from app.schemas.consultation import GeneratedConsultationDocument


def _settings(**overrides) -> EmailSettings:
    values = {
        'email': 'sender@example.com',
        'host_name': 'smtp.example.com',
        'port': 465,
        'application_key': 'secret-password',
        'smtp_max_attempts': 3,
        'smtp_retry_base_delay_seconds': 0,
        'smtp_retry_max_delay_seconds': 0,
    }
    values.update(overrides)
    return EmailSettings(**values)


def _document() -> GeneratedConsultationDocument:
    return GeneratedConsultationDocument(
        filename='Консультация — Права при увольнении — 2026-08-06.pdf',
        content=b'%PDF-test-content',
    )


def test_build_message_contains_alternative_bodies_and_pdf_attachment():
    client = SmtpClient(_settings())

    message = client.build_message(
        recipient='user@example.com',
        document=_document(),
    )

    assert isinstance(message, EmailMessage)
    assert str(message['From']).endswith('<sender@example.com>')
    assert str(message['To']) == 'user@example.com'
    assert message['Date']
    assert message['Message-ID']
    assert message.get_body(preferencelist=('plain',)).get_content_type() == 'text/plain'
    assert message.get_body(preferencelist=('html',)).get_content_type() == 'text/html'
    plain_body = message.get_body(preferencelist=('plain',)).get_content()
    html_body = message.get_body(preferencelist=('html',)).get_content()
    assert 'Ассистента Веры' in plain_body
    assert 'Ассистента Веры' in html_body
    assert 'Документ содержит текстовый слой' not in plain_body
    assert 'Документ содержит текстовый слой' not in html_body
    (attachment,) = list(message.iter_attachments())
    assert attachment.get_content_type() == 'application/pdf'
    assert attachment.get_filename() == (
        'Консультация — Права при увольнении — 2026-08-06.pdf'
    )
    assert attachment.get_payload(decode=True) == b'%PDF-test-content'


async def test_send_document_retries_transient_error_and_keeps_message_id(monkeypatch):
    client = SmtpClient(_settings())
    seen_message_ids = []
    attempts = 0

    async def fake_send_once(message):
        nonlocal attempts
        attempts += 1
        seen_message_ids.append(str(message['Message-ID']))
        if attempts == 1:
            raise ConnectionResetError('connection reset')

    monkeypatch.setattr(client, '_send_once', fake_send_once)

    successful_attempt = await client.send_document(
        recipient='user@example.com',
        document=_document(),
    )

    assert successful_attempt == 2
    assert seen_message_ids[0] == seen_message_ids[1]


async def test_send_document_does_not_retry_permanent_smtp_error(monkeypatch):
    client = SmtpClient(_settings())
    attempts = 0

    async def fake_send_once(message):
        nonlocal attempts
        attempts += 1
        raise SMTPResponseException(550, 'recipient rejected')

    monkeypatch.setattr(client, '_send_once', fake_send_once)

    with pytest.raises(
        ConsultationEmailDeliveryError,
        match='smtp_5xx',
    ) as error_info:
        await client.send_document(
            recipient='user@example.com',
            document=_document(),
        )

    assert error_info.value.attempts == 1
    assert attempts == 1


async def test_send_document_does_not_retry_authentication_error(monkeypatch):
    client = SmtpClient(_settings())

    async def fake_send_once(message):
        raise SMTPAuthenticationError(535, 'authentication failed')

    monkeypatch.setattr(client, '_send_once', fake_send_once)

    with pytest.raises(
        ConsultationEmailDeliveryError,
        match='authentication',
    ) as error_info:
        await client.send_document(
            recipient='user@example.com',
            document=_document(),
        )

    assert error_info.value.attempts == 1


async def test_send_document_exhausts_transient_attempts(monkeypatch):
    client = SmtpClient(_settings(smtp_max_attempts=3))
    attempts = 0

    async def fake_send_once(message):
        nonlocal attempts
        attempts += 1
        raise ConnectionResetError('connection reset')

    monkeypatch.setattr(client, '_send_once', fake_send_once)

    with pytest.raises(
        ConsultationEmailDeliveryError,
        match='network',
    ) as error_info:
        await client.send_document(
            recipient='user@example.com',
            document=_document(),
        )

    assert attempts == 3
    assert error_info.value.attempts == 3


def test_recipient_refusal_classification_distinguishes_4xx_and_5xx():
    transient = SMTPRecipientsRefused(
        [SMTPRecipientRefused(450, 'try later', 'user@example.com')]
    )
    permanent = SMTPRecipientsRefused(
        [SMTPRecipientRefused(550, 'unknown user', 'user@example.com')]
    )

    assert SmtpClient._classify_error(transient) == (
        True,
        'recipient_transient',
    )
    assert SmtpClient._classify_error(permanent) == (
        False,
        'recipient_rejected',
    )


async def test_quit_failure_after_accepted_message_does_not_retry(monkeypatch):
    instances = []

    class FakeSmtp:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.send_calls = 0
            self.closed = False
            instances.append(self)

        async def connect(self):
            return None

        async def login(self, username, password):
            assert username == 'sender@example.com'
            assert password == 'secret-password'

        async def send_message(self, message, timeout):
            self.send_calls += 1

        async def quit(self, timeout):
            raise ConnectionResetError('connection closed after DATA')

        def close(self):
            self.closed = True

    monkeypatch.setattr(smtp_client_module.aiosmtplib, 'SMTP', FakeSmtp)
    client = SmtpClient(_settings())

    successful_attempt = await client.send_document(
        recipient='user@example.com',
        document=_document(),
    )

    assert successful_attempt == 1
    assert len(instances) == 1
    assert instances[0].send_calls == 1
    assert instances[0].closed is True
    assert instances[0].kwargs['use_tls'] is True

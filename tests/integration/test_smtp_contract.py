"""SMTP-контракт через настоящий локальный TCP-сокет без внешней почты."""

import asyncio
from email import policy
from email.parser import BytesParser

from app.clients.smtp_client import SmtpClient
from app.core.settings import EmailSettings
from app.schemas.consultation import GeneratedConsultationDocument


class LocalSmtpServer:
    def __init__(self):
        self.message_bytes: asyncio.Future[bytes] = (
            asyncio.get_running_loop().create_future()
        )

    async def handle(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        writer.write(b'220 localhost ESMTP consultation-test\r\n')
        await writer.drain()
        data_mode = False
        message_lines: list[bytes] = []
        login_password_expected = False

        try:
            while line := await reader.readline():
                command = line.rstrip(b'\r\n')
                upper_command = command.upper()

                if data_mode:
                    if command == b'.':
                        data_mode = False
                        message = b''.join(message_lines)
                        if not self.message_bytes.done():
                            self.message_bytes.set_result(message)
                        writer.write(b'250 2.0.0 accepted\r\n')
                    else:
                        if command.startswith(b'..'):
                            command = command[1:]
                        message_lines.append(command + b'\r\n')
                    await writer.drain()
                    continue

                if login_password_expected:
                    login_password_expected = False
                    writer.write(b'235 2.7.0 authenticated\r\n')
                elif upper_command.startswith((b'EHLO ', b'HELO ')):
                    writer.write(
                        b'250-localhost\r\n'
                        b'250-AUTH PLAIN LOGIN\r\n'
                        b'250 SIZE 10000000\r\n'
                    )
                elif upper_command.startswith(b'AUTH PLAIN'):
                    writer.write(b'235 2.7.0 authenticated\r\n')
                elif upper_command.startswith(b'AUTH LOGIN'):
                    login_password_expected = True
                    writer.write(b'334 UGFzc3dvcmQ6\r\n')
                elif upper_command.startswith((b'MAIL FROM:', b'RCPT TO:')):
                    writer.write(b'250 2.1.0 ok\r\n')
                elif upper_command == b'DATA':
                    data_mode = True
                    writer.write(b'354 end with <CRLF>.<CRLF>\r\n')
                elif upper_command == b'RSET':
                    writer.write(b'250 2.0.0 reset\r\n')
                elif upper_command == b'QUIT':
                    writer.write(b'221 2.0.0 bye\r\n')
                    await writer.drain()
                    break
                else:
                    writer.write(b'500 5.5.1 unsupported command\r\n')
                await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()


async def test_smtp_client_sends_parseable_unicode_pdf_over_local_socket():
    smtp_server = LocalSmtpServer()
    server = await asyncio.start_server(
        smtp_server.handle,
        host='127.0.0.1',
        port=0,
    )
    port = server.sockets[0].getsockname()[1]
    document = GeneratedConsultationDocument(
        filename='консультация-вера.pdf',
        content=b'%PDF-local-smtp-contract',
    )
    client = SmtpClient(
        EmailSettings(
            email='sender@example.com',
            host_name='127.0.0.1',
            port=port,
            application_key='test-password',
            smtp_use_tls=False,
            smtp_start_tls=False,
            smtp_max_attempts=1,
        )
    )

    try:
        attempt = await client.send_document(
            recipient='user@example.com',
            document=document,
        )
        raw_message = await asyncio.wait_for(
            smtp_server.message_bytes,
            timeout=2,
        )
    finally:
        server.close()
        await server.wait_closed()

    parsed = BytesParser(policy=policy.default).parsebytes(raw_message)
    attachments = list(parsed.iter_attachments())

    assert attempt == 1
    assert str(parsed['To']) == 'user@example.com'
    assert str(parsed['Subject']) == (
        'Ваша консультация от Ассистента Веры'
    )
    assert parsed.get_body(preferencelist=('plain',)) is not None
    assert parsed.get_body(preferencelist=('html',)) is not None
    assert len(attachments) == 1
    assert attachments[0].get_content_type() == 'application/pdf'
    assert attachments[0].get_filename() == document.filename
    assert attachments[0].get_payload(decode=True) == document.content

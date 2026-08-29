import json
from unittest.mock import AsyncMock

import pytest
from mcp.server.fastmcp import FastMCP
from pydantic import ValidationError

from app.schemas.consultation import (
    ConsultationSendError,
    ConsultationSendSuccess,
)
from app.services.consultation_delivery import ConsultationDeliveryService
from app.tools.send_consultation_email import register_send_consultation_email


def _mcp(service: AsyncMock) -> FastMCP:
    mcp = FastMCP('test-consultation-email')
    register_send_consultation_email(mcp, service)
    return mcp


def test_success_contract_forbids_returning_email():
    with pytest.raises(ValidationError):
        ConsultationSendSuccess(
            document_name='consultation.pdf',
            email='private-user@example.com',
        )


async def test_tool_public_schema_contains_text_topic_and_email():
    service = AsyncMock(spec=ConsultationDeliveryService)
    mcp = _mcp(service)

    (tool,) = await mcp.list_tools()

    assert tool.name == 'send_consultation_email'
    assert set(tool.inputSchema['properties']) == {
        'consultation_text',
        'consultation_topic',
        'email',
    }
    assert 'явной просьбы' in tool.description
    assert 'Не повторяй' in tool.description


async def test_tool_delegates_without_formatting_and_serializes_success():
    service = AsyncMock(spec=ConsultationDeliveryService)
    service.send.return_value = ConsultationSendSuccess(
        document_name='consultation.pdf',
    )
    mcp = _mcp(service)

    result = await mcp.call_tool(
        'send_consultation_email',
        {
            'consultation_text': 'Исходный текст.',
            'consultation_topic': 'Права при увольнении',
            'email': 'user@example.com',
        },
    )

    service.send.assert_awaited_once_with(
        consultation_text='Исходный текст.',
        consultation_topic='Права при увольнении',
        email='user@example.com',
    )
    assert json.loads(result[0].text) == {
        'status': 'ok',
        'document_name': 'consultation.pdf',
        'message': 'Консультация успешно отправлена.',
    }
    assert 'user@example.com' not in result[0].text


async def test_tool_returns_business_error_as_regular_result():
    service = AsyncMock(spec=ConsultationDeliveryService)
    service.send.return_value = ConsultationSendError(
        code='invalid_email',
        message='Указан некорректный адрес электронной почты.',
    )
    mcp = _mcp(service)

    result = await mcp.call_tool(
        'send_consultation_email',
        {
            'consultation_text': 'Текст.',
            'consultation_topic': 'Права при увольнении',
            'email': 'invalid',
        },
    )

    assert json.loads(result[0].text) == {
        'status': 'error',
        'code': 'invalid_email',
        'message': 'Указан некорректный адрес электронной почты.',
    }

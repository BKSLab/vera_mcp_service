"""Реальный MCP/streamable-http контракт мутирующей тулы консультации."""

import asyncio
import json
import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from langchain_mcp_adapters.client import MultiServerMCPClient
from mcp.server.fastmcp import FastMCP
from sse_starlette.sse import AppStatus

from app.schemas.consultation import (
    ConsultationSendError,
    ConsultationSendSuccess,
)
from app.tools.send_consultation_email import register_send_consultation_email


class FakeDeliveryService:
    async def send(
        self,
        *,
        consultation_text: str,
        consultation_topic: str,
        email: str,
    ):
        if '@' not in email:
            return ConsultationSendError(
                code='invalid_email',
                message='Указан некорректный адрес электронной почты.',
            )
        local_part = email.split('@', maxsplit=1)[0]
        return ConsultationSendSuccess(
            document_name=f'consultation-{local_part}.pdf',
        )


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as temp_socket:
        temp_socket.bind(('127.0.0.1', 0))
        return temp_socket.getsockname()[1]


@asynccontextmanager
async def _run_server() -> AsyncIterator[str]:
    mcp = FastMCP('vera-tools', stateless_http=True)
    register_send_consultation_email(mcp, FakeDeliveryService())
    app = mcp.streamable_http_app()
    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(app, host='127.0.0.1', port=port, log_level='warning')
    )
    server_task = asyncio.create_task(server.serve())
    try:
        while not server.started:
            await asyncio.sleep(0.02)
        yield f'http://127.0.0.1:{port}/mcp'
    finally:
        server.should_exit = True
        await server_task
        AppStatus.should_exit = False


def _parse_result(raw_result: object) -> dict:
    assert isinstance(raw_result, list) and raw_result
    return json.loads(raw_result[0]['text'])


async def test_consultation_tool_success_error_and_concurrency_over_real_protocol():
    async with _run_server() as url:
        client = MultiServerMCPClient(
            {
                'vera-tools': {
                    'url': url,
                    'transport': 'streamable_http',
                    'timeout': 10.0,
                }
            },
            handle_tool_errors=False,
        )
        tools = await client.get_tools()
        (tool,) = [item for item in tools if item.name == 'send_consultation_email']

        invalid = await tool.ainvoke(
            {
                'consultation_text': 'Текст.',
                'consultation_topic': 'Трудовые права',
                'email': 'invalid',
            }
        )
        assert _parse_result(invalid)['code'] == 'invalid_email'

        emails = [f'user-{index}@example.com' for index in range(20)]
        results = await asyncio.gather(
            *(
                tool.ainvoke(
                    {
                        'consultation_text': f'Консультация {index}.',
                        'consultation_topic': f'Трудовые права {index}',
                        'email': email,
                    }
                )
                for index, email in enumerate(emails)
            )
        )

    parsed = [_parse_result(result) for result in results]
    assert all('email' not in result for result in parsed)
    assert not any(
        email in json.dumps(parsed, ensure_ascii=False)
        for email in emails
    )
    assert [result['document_name'] for result in parsed] == [
        f'consultation-user-{index}.pdf' for index in range(20)
    ]

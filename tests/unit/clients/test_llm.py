import json
import logging

import httpx
import pytest

from app.clients.llm import LlmClient, logger
from app.exceptions.llm import LlmApiRequestError
from app.schemas.consultation import PreparedConsultation


def _client(http_client: httpx.AsyncClient, **overrides) -> LlmClient:
    defaults = {
        'httpx_client': http_client,
        'model': 'test-model',
        'url': 'https://llm.test/v1/chat/completions',
        'headers': {
            'Authorization': 'Bearer secret-key',
            'Content-Type': 'application/json',
        },
        'temperature': 0.1,
        'timeout': 2,
        'retries': 2,
        'delay': 0,
        'max_delay': 0,
        'use_json_mode': True,
        'extra_payload': {'reasoning': {'effort': 'high'}},
    }
    defaults.update(overrides)
    return LlmClient(**defaults)


def _valid_content() -> dict:
    return {
        'title': 'Консультация',
        'intro': ['Вступление.'],
        'sections': [],
        'conclusion': [],
        'sources': [],
    }


async def test_llm_client_sends_separate_messages_and_returns_schema():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured['authorization'] = request.headers['Authorization']
        captured['payload'] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                'choices': [
                    {'message': {'content': json.dumps(_valid_content(), ensure_ascii=False)}}
                ]
            },
        )

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = _client(http_client)

    result = await client.get_llm_response(
        '<INPUT_DATA>исходный текст</INPUT_DATA>',
        'system prompt',
        schema=PreparedConsultation,
    )

    assert isinstance(result, PreparedConsultation)
    assert captured['authorization'] == 'Bearer secret-key'
    assert captured['payload']['messages'] == [
        {'role': 'system', 'content': 'system prompt'},
        {'role': 'user', 'content': '<INPUT_DATA>исходный текст</INPUT_DATA>'},
    ]
    assert captured['payload']['response_format'] == {'type': 'json_object'}
    assert captured['payload']['reasoning']['effort'] == 'high'
    assert 'max_completion_tokens' not in captured['payload']
    await http_client.aclose()


async def test_llm_client_retries_invalid_content_then_succeeds():
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        content = '{}' if attempts == 1 else json.dumps(_valid_content(), ensure_ascii=False)
        return httpx.Response(200, json={'choices': [{'message': {'content': content}}]})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = _client(http_client)

    result = await client.get_llm_response(
        'text',
        'prompt',
        schema=PreparedConsultation,
    )

    assert isinstance(result, PreparedConsultation)
    assert attempts == 2
    await http_client.aclose()


async def test_llm_client_retries_non_json_response_then_succeeds():
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(200, text='not-json')
        return httpx.Response(
            200,
            json={
                'choices': [
                    {
                        'message': {
                            'content': json.dumps(
                                _valid_content(),
                                ensure_ascii=False,
                            )
                        }
                    }
                ]
            },
        )

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = _client(http_client)

    result = await client.get_llm_response(
        'text',
        'prompt',
        schema=PreparedConsultation,
    )

    assert isinstance(result, PreparedConsultation)
    assert attempts == 2
    await http_client.aclose()


@pytest.mark.parametrize(
    'response_json',
    [
        [],
        {'choices': []},
        {'choices': [{'message': None}]},
        {'choices': [{'message': {'content': ['unexpected', 'parts']}}]},
    ],
)
async def test_llm_client_maps_unexpected_response_shapes_to_final_error(
    response_json,
):
    http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=response_json)
        )
    )
    client = _client(http_client, retries=1)

    with pytest.raises(LlmApiRequestError):
        await client.get_llm_response('private text', 'prompt')

    await http_client.aclose()


async def test_llm_client_can_disable_json_mode():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured['payload'] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                'choices': [
                    {'message': {'content': json.dumps(_valid_content())}}
                ]
            },
        )

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = _client(http_client, use_json_mode=False)

    await client.get_llm_response('text', 'prompt', schema=PreparedConsultation)

    assert 'response_format' not in captured['payload']
    await http_client.aclose()


async def test_llm_http_error_body_is_not_logged(
    caplog,
    monkeypatch,
):
    sensitive_response = 'PRIVATE_CONSULTATION_RESPONSE'
    http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(400, text=sensitive_response)
        )
    )
    client = _client(http_client, retries=1)
    monkeypatch.setattr(logger, 'propagate', True)

    with caplog.at_level(logging.ERROR, logger=logger.name):
        with pytest.raises(LlmApiRequestError):
            await client.get_llm_response('private text', 'prompt')

    assert sensitive_response not in caplog.text
    assert 'HTTP 400' in caplog.text
    await http_client.aclose()


async def test_llm_client_raises_after_transport_attempts_exhausted():
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ConnectError('secret response must not leak', request=request)

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = _client(http_client, retries=3)

    with pytest.raises(LlmApiRequestError, match='LLM API'):
        await client.get_llm_response('private text', 'prompt')

    assert attempts == 3
    await http_client.aclose()

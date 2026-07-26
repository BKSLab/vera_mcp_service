import asyncio
import functools
import json
import random
from collections.abc import Callable
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.core.config_logger import logger
from app.exceptions.llm import (
    LlmApiRequestError,
    LlmClientContentError,
    LlmClientRequestError,
)

PydanticModel = TypeVar('PydanticModel', bound=BaseModel)


class LlmClient:
    """Клиент для LLM API, совместимых с OpenAI Chat Completions."""

    DEFAULT_TIMEOUT_SECONDS: int = 90
    DEFAULT_RETRIES: int = 3
    DEFAULT_RETRY_DELAY: float = 1.0
    DEFAULT_MAX_RETRY_DELAY: float = 30.0
    JITTER_RATIO: float = 0.1

    def __init__(
        self,
        httpx_client: httpx.AsyncClient,
        model: str,
        url: str,
        headers: dict,
        temperature: float = 0.3,
        stream: bool = False,
        timeout: int = DEFAULT_TIMEOUT_SECONDS,
        retries: int = DEFAULT_RETRIES,
        delay: float = DEFAULT_RETRY_DELAY,
        max_delay: float = DEFAULT_MAX_RETRY_DELAY,
        use_json_mode: bool = True,
        extra_payload: dict | None = None,
    ):
        self.httpx_client = httpx_client
        self.model = model
        self.url = url
        self.headers = headers
        self.temperature = temperature
        self.stream = stream
        self.timeout = timeout
        self.retries = retries
        self.delay = delay
        self.max_delay = max_delay
        self.use_json_mode = use_json_mode
        self.extra_payload = extra_payload or {}

    def _get_backoff_delay(self, attempt: int) -> float:
        base_delay = min(self.max_delay, self.delay * (2 ** (attempt - 1)))
        jitter = base_delay * self.JITTER_RATIO * random.random()
        return base_delay + jitter

    async def _send_request_to_llm(self, payload: dict) -> dict:
        data_json = json.dumps(payload, ensure_ascii=False)
        try:
            logger.info('📤 Отправка запроса к LLM, модель: %s', payload.get('model'))
            response = await self.httpx_client.post(
                url=self.url,
                headers=self.headers,
                data=data_json,
                timeout=self.timeout,
            )
            response.raise_for_status()
            try:
                parsed_response = response.json()
            except json.JSONDecodeError as error:
                raise LlmClientContentError(
                    'LLM вернул ответ, который не является JSON'
                ) from error
            if not isinstance(parsed_response, dict):
                raise LlmClientContentError(
                    'LLM вернул JSON неожиданного верхнего уровня'
                )
            return parsed_response
        except httpx.HTTPStatusError as error:
            logger.error(
                '🌐 HTTP %s от LLM',
                error.response.status_code,
            )
            raise LlmClientRequestError(
                f'HTTP {error.response.status_code}'
            ) from error
        except httpx.TimeoutException as error:
            logger.error(
                '⏱️ Таймаут при запросе к LLM (%ss): %s',
                self.timeout,
                error,
            )
            raise LlmClientRequestError('Таймаут запроса к LLM') from error
        except httpx.RequestError as error:
            logger.error(
                '🌐 Сетевая ошибка при запросе к LLM: %s: %s',
                type(error).__name__,
                error,
            )
            raise LlmClientRequestError(
                f'Сетевая ошибка: {type(error).__name__}'
            ) from error

    def _extract_content(self, response: dict) -> str:
        try:
            choices = response['choices']
            message = choices[0]['message']
            content = message['content']
        except (KeyError, IndexError, TypeError) as error:
            logger.debug(
                'Структура ответа LLM невалидна: %s',
                type(error).__name__,
            )
            raise LlmClientContentError(
                f'Невалидная структура ответа LLM: {type(error).__name__}'
            ) from error

        if not isinstance(content, str):
            raise LlmClientContentError('Контент LLM должен быть строкой')
        if not content.strip():
            raise LlmClientContentError('LLM вернул пустой ответ')
        return content

    def _extract_validated(
        self,
        response: dict,
        schema: type[PydanticModel],
    ) -> PydanticModel:
        content = self._extract_content(response)
        try:
            return schema.model_validate_json(content)
        except ValidationError as error:
            logger.warning(
                '📋 Ответ LLM не прошёл валидацию схемы %s: %s',
                schema.__name__,
                error,
            )
            raise LlmClientContentError(
                f'Ответ не соответствует схеме {schema.__name__}'
            ) from error

    async def _fetch_with_retries(
        self,
        payload: dict,
        extractor: Callable[[dict], Any],
    ) -> Any:
        last_error: Exception | None = None

        for attempt in range(1, self.retries + 1):
            try:
                response = await self._send_request_to_llm(payload)
                content = extractor(response)
                if attempt > 1:
                    logger.info('✅ Ответ от LLM получен с %s-й попытки', attempt)
                return content
            except LlmClientContentError as error:
                last_error = error
                logger.warning(
                    '📭 Некорректный контент от LLM (попытка %d/%d): %s',
                    attempt,
                    self.retries,
                    error,
                )
            except LlmClientRequestError as error:
                last_error = error
                logger.warning(
                    '⚠️ Ошибка запроса к LLM (попытка %d/%d): %s',
                    attempt,
                    self.retries,
                    error,
                )

            if attempt < self.retries:
                delay = self._get_backoff_delay(attempt)
                logger.info(
                    '🔄 Повтор через %.1fс (следующая попытка: %d/%d)',
                    delay,
                    attempt + 1,
                    self.retries,
                )
                await asyncio.sleep(delay)

        logger.error(
            '❌ Не удалось получить ответ от LLM после %d попыток. '
            'Последняя ошибка: %s',
            self.retries,
            last_error,
        )
        raise LlmApiRequestError(
            error_details=str(last_error),
            request_url=self.url,
        )

    async def get_llm_response(
        self,
        content: str,
        prompt: str,
        model: str | None = None,
        schema: type[PydanticModel] | None = None,
    ) -> str | PydanticModel:
        """Возвращает текст либо результат, валидированный Pydantic-схемой.

        Лимит completion tokens намеренно не задаётся: объём консультации
        определяется реальным содержимым, переданным Agent Service.
        """
        payload = {
            'model': model or self.model,
            'messages': [
                {'role': 'system', 'content': prompt},
                {'role': 'user', 'content': content},
            ],
            'temperature': self.temperature,
            'stream': self.stream,
        }
        if schema and self.use_json_mode:
            payload['response_format'] = {'type': 'json_object'}
        if self.extra_payload:
            payload.update(self.extra_payload)

        extractor = (
            functools.partial(self._extract_validated, schema=schema)
            if schema
            else self._extract_content
        )
        return await self._fetch_with_retries(payload, extractor=extractor)

import logging

import httpx

from app.core.settings import RagClientSettings
from app.exceptions.rag import RagUnavailableError

logger = logging.getLogger('vera_mcp_service')

SEARCH_PATH = '/api/v1/search'


class RagClient:
    """Клиент RAG Service (`POST /api/v1/search`, `vera_rag_service/README.md`).

    Не ретраит сам — Agent Service уже ретраит вызов тула целиком, а RAG
    Service ретраит embedding/reranker внутри себя; собственный слой
    ретраев здесь был бы "ретраями в квадрате" (MCP_SERVICE_PLAN.md, раздел 0.1).
    """

    def __init__(self, httpx_client: httpx.AsyncClient, settings: RagClientSettings) -> None:
        self._httpx_client = httpx_client
        self._settings = settings

    async def search(self, query: str, audience: str, top_k: int) -> dict:
        """Семантический поиск по базе знаний.

        Args:
            query: текст запроса пользователя.
            audience: `'seeker' | 'employer' | 'both'`.
            top_k: сколько чанков вернуть после переранжирования.

        Returns:
            `{"chunks": [...]}` — пустой список `chunks` валиден ("нет ответа
            на этот вопрос"), не ошибка.

        Raises:
            RagUnavailableError: сеть/таймаут/`5xx`/`429`/неожиданный формат
                ответа — единое исключение для вызывающего тула, который
                должен пробросить его дальше, не превращать в `dict` с
                полем ошибки (MCP_SERVICE_PLAN.md, раздел 0.1).
        """
        # Не логируем текст query на INFO — потенциально чувствительные
        # данные о здоровье/инвалидности (MCP_SERVICE_PLAN.md, раздел 0.3).
        logger.info('🔍 Запрос к RAG Service: query_length=%d audience=%r top_k=%d', len(query), audience, top_k)

        try:
            response = await self._httpx_client.post(
                f'{self._settings.rag_service_url}{SEARCH_PATH}',
                json={'query': query, 'audience': audience, 'top_k': top_k},
                headers={'X-API-Key': self._settings.rag_service_api_key.get_secret_value()},
                timeout=self._settings.rag_search_timeout_seconds,
            )
        except httpx.HTTPError as error:
            logger.warning('⚠️ RAG Service недоступен (сеть/таймаут): %s', error)
            raise RagUnavailableError(str(error)) from error

        if response.status_code >= 400:
            logger.warning('⚠️ RAG Service вернул ошибку %d: %s', response.status_code, response.text)
            raise RagUnavailableError(f'HTTP {response.status_code}: {response.text}')

        try:
            payload = response.json()
        except ValueError as error:
            logger.warning('⚠️ RAG Service вернул невалидный JSON: %s', error)
            raise RagUnavailableError(f'Невалидный JSON в ответе: {error}') from error

        if not isinstance(payload, dict) or 'chunks' not in payload:
            logger.warning('⚠️ RAG Service вернул ответ без поля chunks: %r', payload)
            raise RagUnavailableError(f'Неожиданный формат ответа: {payload!r}')

        logger.info('✅ RAG Service вернул %d чанков', len(payload['chunks']))
        return payload

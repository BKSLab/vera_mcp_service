import logging
from collections.abc import Awaitable, Callable

logger = logging.getLogger('vera_mcp_service')

HealthCheck = Callable[[], Awaitable[bool]]


class HealthRegistry:
    """Реестр проверок здоровья внешних зависимостей.

    Тот же принцип, что и реестр тулов (`app/tools/__init__.py`,
    MCP_SERVICE_PLAN.md, раздел 0.3): при добавлении новой внешней
    интеграции (Dadata, векторный поиск и т.д. — итерация 2) достаточно
    одного `register(name, check)`, без переписывания существующей логики
    `GET /health`.
    """

    def __init__(self) -> None:
        self._checks: dict[str, HealthCheck] = {}

    def register(self, name: str, check: HealthCheck) -> None:
        self._checks[name] = check

    async def run(self) -> dict[str, str]:
        """Выполняет все зарегистрированные проверки.

        Недоступность зависимости — не повод падать самим `GET /health`
        (MCP_SERVICE_PLAN.md, Этап 4) — код ответа всегда `200`, статус
        конкретной зависимости отражается в теле.
        """
        statuses: dict[str, str] = {}
        for name, check in self._checks.items():
            try:
                healthy = await check()
            except Exception as error:
                logger.warning('⚠️ Health-check %r упал с исключением: %s', name, error)
                healthy = False
            statuses[name] = 'ok' if healthy else 'unreachable'
        return statuses

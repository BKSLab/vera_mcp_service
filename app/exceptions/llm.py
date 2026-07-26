class LlmClientRequestError(Exception):
    """Ошибка одной попытки обращения к OpenAI-совместимому LLM API."""


class LlmClientContentError(Exception):
    """Ответ LLM получен, но его содержимое нельзя использовать."""


class LlmApiRequestError(Exception):
    """Все настроенные попытки обращения к LLM завершились неуспешно."""

    def __init__(self, error_details: str, request_url: str):
        self.error_details = error_details
        self.request_url = request_url
        super().__init__(self.error_details, self.request_url)

    def __str__(self) -> str:
        return (
            f'Ошибка запроса к LLM API. URL: {self.request_url}. '
            f'Подробности: {self.error_details}'
        )

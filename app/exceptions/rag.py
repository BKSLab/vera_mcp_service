class RagUnavailableError(Exception):
    """RAG Service недоступен — сетевая ошибка, таймаут, `5xx`/`429` или
    неожиданный формат ответа `POST /api/v1/search` (`app/clients/rag_client.py`).

    Единое исключение для всех перечисленных сценариев одной попытки — для
    вызывающего тула (`app/tools/kb_search.py`) все они означают одно и то
    же: результат недоступен (MCP_SERVICE_PLAN.md, раздел 0.1). `422` из
    RAG в норме не должен возникать от наших запросов — валидация
    аргументов отсекается раньше, на уровне самого тула.

    Не перехватывается внутри тула — должна всплыть наружу как исключение
    MCP-уровня (раздел 0.1): `MultiServerMCPClient(handle_tool_errors=False)`
    на стороне Agent Service ждёт именно исключение, а не `dict` с полем
    ошибки, иначе его логика деградации не сработает.
    """

    def __init__(self, error_details: str):
        self.error_details = error_details
        super().__init__(self.error_details)

    def __str__(self) -> str:
        return f'RAG Service недоступен. Подробности: {self.error_details}'

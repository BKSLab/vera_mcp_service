class ConsultationFormattingError(Exception):
    """LLM не смогла структурировать консультацию после всех попыток."""


class ConsultationPdfGenerationError(Exception):
    """Не удалось сформировать PDF из подготовленной консультации."""


class ConsultationEmailDeliveryError(Exception):
    """SMTP-сервер не подтвердил доставку письма после допустимых попыток."""

    def __init__(self, error_category: str, attempts: int):
        self.error_category = error_category
        self.attempts = attempts
        super().__init__(error_category, attempts)

    def __str__(self) -> str:
        return (
            'Не удалось подтвердить отправку письма: '
            f'категория={self.error_category}, попыток={self.attempts}'
        )

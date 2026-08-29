from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

TitleText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
]
ConsultationTopic = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=120),
]
HeadingText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
]
ParagraphText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
]
BulletText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
]
SourceText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
]


class ConsultationSection(BaseModel):
    """Один смысловой раздел консультации без HTML и Markdown."""

    model_config = ConfigDict(extra='forbid')

    heading: HeadingText = Field(
        description='Краткий заголовок раздела, отражающий исходный текст.',
        examples=['Что важно учесть'],
    )
    paragraphs: list[ParagraphText] = Field(
        default_factory=list,
        description='Абзацы раздела в исходном смысловом порядке.',
        examples=[['Первый абзац.', 'Второй абзац.']],
    )
    bullet_points: list[BulletText] = Field(
        default_factory=list,
        description='Только перечисления, которые присутствуют в исходном тексте.',
        examples=[['Подготовить документы', 'Уточнить время встречи']],
    )

    @model_validator(mode='after')
    def validate_content(self) -> 'ConsultationSection':
        if not self.paragraphs and not self.bullet_points:
            raise ValueError('Раздел должен содержать абзац или пункт списка')
        return self


class ConsultationContent(BaseModel):
    """Структурированное содержимое консультации без заголовка документа."""

    model_config = ConfigDict(extra='forbid')

    intro: list[ParagraphText] = Field(
        default_factory=list,
        description='Короткое вступление из исходного текста.',
    )
    sections: list[ConsultationSection] = Field(
        default_factory=list,
        description='Логические разделы в порядке исходной консультации.',
    )
    conclusion: list[ParagraphText] = Field(
        default_factory=list,
        description='Итоговые абзацы, если они есть в исходном тексте.',
    )
    sources: list[SourceText] = Field(
        default_factory=list,
        description='Источники и ссылки только из исходного текста.',
    )

    @field_validator('intro', 'conclusion', 'sources')
    @classmethod
    def reject_duplicate_items(cls, values: list[str]) -> list[str]:
        """Сохраняет порядок, но удаляет случайные точные повторы LLM."""
        return list(dict.fromkeys(values))

    @model_validator(mode='after')
    def validate_meaningful_content(self) -> 'ConsultationContent':
        if not self.intro and not self.sections and not self.conclusion:
            raise ValueError('Консультация не содержит ни одного смыслового блока')
        return self


class FormattedConsultation(ConsultationContent):
    """Результат LLM-структурирования без темы, которую задаёт агент."""


class PreparedConsultation(ConsultationContent):
    """Готовая структура с темой для формирования документа."""

    title: TitleText = Field(
        description='Тема консультации без имени пользователя и email.',
        examples=['Права при увольнении'],
    )


class GeneratedConsultationDocument(BaseModel):
    """Готовый документ в памяти; локального файла с консультацией нет."""

    model_config = ConfigDict(extra='forbid')

    filename: str = Field(min_length=1, max_length=255)
    content: bytes = Field(min_length=5)
    content_type: Literal['application/pdf'] = 'application/pdf'

    @property
    def size_bytes(self) -> int:
        return len(self.content)


class ConsultationSendSuccess(BaseModel):
    model_config = ConfigDict(extra='forbid')

    status: Literal['ok'] = 'ok'
    document_name: str
    message: Literal['Консультация успешно отправлена.'] = (
        'Консультация успешно отправлена.'
    )


ConsultationErrorCode = Literal[
    'invalid_email',
    'invalid_consultation_text',
    'invalid_consultation_topic',
    'consultation_formatting_failed',
    'pdf_generation_failed',
    'email_delivery_failed',
]


class ConsultationSendError(BaseModel):
    model_config = ConfigDict(extra='forbid')

    status: Literal['error'] = 'error'
    code: ConsultationErrorCode
    message: str


ConsultationSendResult = ConsultationSendSuccess | ConsultationSendError

import pytest
from pydantic import ValidationError

from app.schemas.consultation import PreparedConsultation


def test_prepared_consultation_accepts_structured_content():
    consultation = PreparedConsultation.model_validate(
        {
            'title': '  Подготовка к работе  ',
            'intro': ['  Краткое вступление.  '],
            'sections': [
                {
                    'heading': 'Что важно',
                    'paragraphs': ['Основной абзац.'],
                    'bullet_points': ['Первый шаг'],
                }
            ],
            'conclusion': [],
            'sources': ['https://example.org', 'https://example.org'],
        }
    )

    assert consultation.title == 'Подготовка к работе'
    assert consultation.intro == ['Краткое вступление.']
    assert consultation.sources == ['https://example.org']


@pytest.mark.parametrize(
    'payload',
    [
        {
            'title': '',
            'intro': ['Текст'],
            'sections': [],
            'conclusion': [],
            'sources': [],
        },
        {
            'title': 'Заголовок',
            'intro': [],
            'sections': [],
            'conclusion': [],
            'sources': [],
        },
        {
            'title': 'Заголовок',
            'intro': [],
            'sections': [
                {
                    'heading': 'Пустой раздел',
                    'paragraphs': [],
                    'bullet_points': [],
                }
            ],
            'conclusion': [],
            'sources': [],
        },
    ],
)
def test_prepared_consultation_rejects_empty_content(payload):
    with pytest.raises(ValidationError):
        PreparedConsultation.model_validate(payload)


def test_prepared_consultation_forbids_extra_fields():
    with pytest.raises(ValidationError):
        PreparedConsultation.model_validate(
            {
                'title': 'Заголовок',
                'intro': ['Текст'],
                'sections': [],
                'conclusion': [],
                'sources': [],
                'html': '<script>alert(1)</script>',
            }
        )

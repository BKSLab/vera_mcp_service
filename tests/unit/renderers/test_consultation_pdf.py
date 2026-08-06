import sys
from datetime import datetime
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.settings import ConsultationSettings
from app.exceptions.consultation import ConsultationPdfGenerationError
from app.renderers.consultation_pdf import ConsultationPdfRenderer
from app.schemas.consultation import PreparedConsultation


def _prepared(text: str = 'Текст консультации.') -> PreparedConsultation:
    return PreparedConsultation(
        title='Безопасный заголовок',
        intro=[text],
        sections=[],
        conclusion=[],
        sources=[
            'https://example.org/accessible-source',
            'javascript:alert(1)',
        ],
    )


async def test_renderer_builds_pdf_bytes_and_escapes_html(monkeypatch):
    captured = {}

    class FakeHtml:
        def __init__(self, *, string, base_url, url_fetcher):
            captured['html'] = string
            captured['base_url'] = base_url
            captured['url_fetcher'] = url_fetcher

        def write_pdf(self, **options):
            captured['options'] = options
            return b'%PDF-fake'

    fake_module = SimpleNamespace(
        HTML=FakeHtml,
        default_url_fetcher=lambda url: {'url': url},
    )
    monkeypatch.setitem(sys.modules, 'weasyprint', fake_module)
    renderer = ConsultationPdfRenderer(
        ConsultationSettings(
            consultation_template_dir=Path('app/templates/consultation'),
            consultation_pdf_render_concurrency=1,
        )
    )

    result = await renderer.render(_prepared('<script>alert(1)</script>'))

    assert result.content == b'%PDF-fake'
    assert result.filename.startswith(
        'Консультация — Безопасный заголовок — '
    )
    assert result.filename.endswith('.pdf')
    assert '<script>' not in captured['html']
    assert '&lt;script&gt;' in captured['html']
    assert (
        '<a href="https://example.org/accessible-source">'
        'https://example.org/accessible-source</a>'
    ) in captured['html']
    assert '<a href="javascript:' not in captured['html']
    assert captured['options']['pdf_tags'] is True
    assert captured['options']['pdf_variant'] == 'pdf/ua-1'


def test_renderer_builds_safe_russian_filename():
    created_at = datetime(2026, 8, 6, 13, 23, 39)

    filename = ConsultationPdfRenderer._build_filename(
        '  Права: отпуск / увольнение?  ',
        created_at,
    )

    assert filename == (
        'Консультация — Права отпуск увольнение — 2026-08-06.pdf'
    )


def test_renderer_rejects_external_resources():
    renderer = ConsultationPdfRenderer(
        ConsultationSettings(
            consultation_template_dir=Path('app/templates/consultation')
        )
    )

    with pytest.raises(
        ConsultationPdfGenerationError,
        match='external_resource_blocked',
    ):
        renderer._local_url_fetcher('https://example.org/image.png', lambda url: url)


async def test_real_renderer_has_russian_text_layer_when_native_libraries_available():
    try:
        import weasyprint  # noqa: F401
    except OSError:
        pytest.skip('Локальный Windows не содержит Pango; проверяется в Docker/CI')

    from pypdf import PdfReader

    renderer = ConsultationPdfRenderer(
        ConsultationSettings(
            consultation_template_dir=Path('app/templates/consultation')
        )
    )
    result = await renderer.render(_prepared('Русский текст для скринридера.'))
    reader = PdfReader(BytesIO(result.content))
    extracted = '\n'.join(page.extract_text() or '' for page in reader.pages)

    assert 'Русский текст для скринридера' in extracted
    assert reader.metadata.title == 'Безопасный заголовок'

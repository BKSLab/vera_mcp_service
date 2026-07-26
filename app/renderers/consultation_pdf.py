import asyncio
import logging
import os
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname
from uuid import uuid4
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from app.core.settings import ConsultationSettings
from app.exceptions.consultation import ConsultationPdfGenerationError
from app.observability.tracing import get_tracer
from app.schemas.consultation import (
    GeneratedConsultationDocument,
    PreparedConsultation,
)

logger = logging.getLogger(__name__)
tracer = get_tracer()


class ConsultationPdfRenderer:
    """Рендерит валидированную структуру в tagged PDF через WeasyPrint."""

    def __init__(self, settings: ConsultationSettings):
        self._settings = settings
        self._template_dir = settings.consultation_template_dir.resolve()
        self._timezone = ZoneInfo(settings.consultation_document_timezone)
        self._semaphore = asyncio.Semaphore(
            settings.consultation_pdf_render_concurrency
        )
        self._environment = Environment(
            loader=FileSystemLoader(self._template_dir),
            autoescape=select_autoescape(enabled_extensions=('html', 'xml')),
            undefined=StrictUndefined,
            enable_async=False,
        )

    async def render(
        self,
        consultation: PreparedConsultation,
    ) -> GeneratedConsultationDocument:
        """Не блокирует event loop синхронной HTML/PDF-вёрсткой."""
        with tracer.start_as_current_span('consultation.pdf.render') as span:
            span.set_attribute('consultation.section_count', len(consultation.sections))
            async with self._semaphore:
                try:
                    document = await asyncio.to_thread(
                        self._render_sync,
                        consultation,
                    )
                except ConsultationPdfGenerationError:
                    span.set_attribute('consultation.outcome', 'error')
                    raise
            span.set_attribute('consultation.outcome', 'ok')
            span.set_attribute('consultation.pdf.size_bytes', document.size_bytes)
            return document

    def _render_sync(
        self,
        consultation: PreparedConsultation,
    ) -> GeneratedConsultationDocument:
        template_path = self._template_dir / 'consultation.html'
        if not template_path.is_file():
            raise ConsultationPdfGenerationError('production_template_missing')

        try:
            from weasyprint import HTML, default_url_fetcher

            now = datetime.now(self._timezone)
            short_id = uuid4().hex[:6]
            filename = (
                f'konsultatsiya-vera-{now:%Y%m%d-%H%M%S}-{short_id}.pdf'
            )
            html = self._environment.get_template('consultation.html').render(
                consultation=consultation,
                created_at_iso=now.isoformat(),
                created_at_display=self._format_date(now),
                document_number=f'VERA-{now:%Y%m%d}-{short_id.upper()}',
            )

            pdf = HTML(
                string=html,
                base_url=f'{self._template_dir.as_uri()}/',
                url_fetcher=lambda url: self._local_url_fetcher(
                    url,
                    default_url_fetcher,
                ),
            ).write_pdf(
                pdf_variant=self._settings.consultation_pdf_variant,
                pdf_tags=True,
                optimize_images=True,
                dpi=150,
            )
        except ConsultationPdfGenerationError:
            raise
        except Exception as error:
            logger.warning(
                '⚠️ PDF-рендер завершился ошибкой: category=%s',
                type(error).__name__,
            )
            raise ConsultationPdfGenerationError(
                f'render_error:{type(error).__name__}'
            ) from error

        if not isinstance(pdf, bytes) or not pdf.startswith(b'%PDF-'):
            raise ConsultationPdfGenerationError('invalid_pdf_output')

        return GeneratedConsultationDocument(
            filename=filename,
            content=pdf,
        )

    def _local_url_fetcher(self, url: str, default_url_fetcher):
        """Разрешает WeasyPrint читать только файлы каталога шаблона."""
        parsed = urlparse(url)
        if parsed.scheme != 'file':
            raise ConsultationPdfGenerationError('external_resource_blocked')

        raw_path = url2pathname(unquote(parsed.path))
        if os.name == 'nt' and raw_path.startswith('\\') and len(raw_path) > 2:
            if raw_path[2] == ':':
                raw_path = raw_path[1:]
        resource_path = Path(raw_path).resolve()

        try:
            resource_path.relative_to(self._template_dir)
        except ValueError as error:
            raise ConsultationPdfGenerationError(
                'resource_outside_template_dir'
            ) from error
        if not resource_path.is_file():
            raise ConsultationPdfGenerationError('template_resource_missing')
        return default_url_fetcher(resource_path.as_uri())

    @staticmethod
    def _format_date(value: datetime) -> str:
        months = (
            'января',
            'февраля',
            'марта',
            'апреля',
            'мая',
            'июня',
            'июля',
            'августа',
            'сентября',
            'октября',
            'ноября',
            'декабря',
        )
        return f'{value.day} {months[value.month - 1]} {value.year} года'

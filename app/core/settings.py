from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, EmailStr, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class SettingsBase(BaseSettings):
    """Базовый класс для всех доменных настроек проекта."""

    model_config = SettingsConfigDict(
        env_file='.env',
        env_file_encoding='utf-8',
        extra='ignore',
    )


class AppSettings(SettingsBase):
    """Общие настройки приложения и запуска MCP-сервера (streamable-http,
    MCP_SERVICE_PLAN.md, раздел 0.1)."""

    app_name: str = 'vera_mcp_service'
    logging_config_path: str = 'logging.ini'
    mcp_service_host: str = '0.0.0.0'
    mcp_service_port: int = 8000


class RagClientSettings(SettingsBase):
    """Настройки клиента к RAG Service (`POST /api/v1/search`,
    `vera_rag_service/README.md`; MCP_SERVICE_PLAN.md, Этап 1)."""

    rag_service_url: str
    rag_service_api_key: SecretStr
    rag_search_timeout_seconds: float = 10.0
    rag_search_top_k: int = 5


class ObservabilitySettings(SettingsBase):
    """Настройки экспорта трейсов в Arize Phoenix (MCP_SERVICE_PLAN.md, Этап 5)."""

    phoenix_enabled: bool = True
    phoenix_otlp_endpoint: str = 'http://localhost:6006/v1/traces'
    phoenix_project_name: str = 'vera-local'


class LlmSettings(SettingsBase):
    """Общий OpenAI-совместимый LLM-клиент для внутренних задач MCP-тулов."""

    llm_api_key: SecretStr
    llm_api_url: str
    consultation_formatting_llm_model: str
    llm_temperature: float = Field(default=0.1, ge=0.0, le=2.0)
    llm_timeout_seconds: float = Field(default=90.0, gt=0)
    llm_retries: int = Field(default=3, ge=1, le=10)
    llm_retry_base_delay_seconds: float = Field(default=1.0, ge=0)
    llm_retry_max_delay_seconds: float = Field(default=30.0, ge=0)
    llm_use_json_mode: bool = True
    llm_reasoning_enabled: bool = True
    llm_reasoning_effort: str = 'high'
    llm_reasoning_summary: str = 'detailed'

    @model_validator(mode='after')
    def validate_retry_delays(self) -> 'LlmSettings':
        if self.llm_retry_max_delay_seconds < self.llm_retry_base_delay_seconds:
            raise ValueError(
                'LLM_RETRY_MAX_DELAY_SECONDS должен быть не меньше '
                'LLM_RETRY_BASE_DELAY_SECONDS'
            )
        return self


class EmailSettings(SettingsBase):
    """SMTP и содержимое письма с консультацией."""

    email: EmailStr
    host_name: str
    port: int = Field(ge=1, le=65535)
    application_key: SecretStr
    smtp_use_tls: bool = True
    smtp_start_tls: bool = False
    smtp_validate_certs: bool = True
    smtp_timeout_seconds: float = Field(default=20.0, gt=0)
    smtp_max_attempts: int = Field(default=3, ge=1, le=10)
    smtp_retry_base_delay_seconds: float = Field(default=1.0, ge=0)
    smtp_retry_max_delay_seconds: float = Field(default=10.0, ge=0)
    consultation_email_subject: str = 'Ваша консультация Веры'
    consultation_email_from_name: str = 'Вера · Работа для всех'

    @model_validator(mode='after')
    def validate_transport(self) -> 'EmailSettings':
        if self.smtp_use_tls and self.smtp_start_tls:
            raise ValueError('SMTP_USE_TLS и SMTP_START_TLS нельзя включать одновременно')
        if self.smtp_retry_max_delay_seconds < self.smtp_retry_base_delay_seconds:
            raise ValueError(
                'SMTP_RETRY_MAX_DELAY_SECONDS должен быть не меньше '
                'SMTP_RETRY_BASE_DELAY_SECONDS'
            )
        if '\r' in self.consultation_email_subject or '\n' in self.consultation_email_subject:
            raise ValueError('CONSULTATION_EMAIL_SUBJECT содержит недопустимый перенос строки')
        return self


class ConsultationSettings(SettingsBase):
    """Внутренние PDF-настройки инструмента отправки консультации."""

    consultation_template_dir: Path = Path('app/templates/consultation')
    consultation_pdf_variant: str = 'pdf/ua-1'
    consultation_pdf_render_concurrency: int = Field(default=2, ge=1, le=16)
    consultation_document_timezone: str = 'Europe/Samara'


class Settings(BaseModel):
    """Агрегатор доменных BaseSettings без повторного чтения process env.

    Сам агрегатор намеренно является BaseModel: переменная EMAIL относится к
    дочернему EmailSettings. Если наследовать агрегатор от BaseSettings,
    Pydantic пытается разобрать EMAIL как JSON для поля ``email`` и сервис
    падает при запуске через Docker Compose/CI, где .env становится process
    environment.
    """

    app: AppSettings = Field(default_factory=AppSettings)
    rag: RagClientSettings = Field(default_factory=RagClientSettings)
    observability: ObservabilitySettings = Field(default_factory=ObservabilitySettings)
    llm: LlmSettings = Field(default_factory=LlmSettings)
    email: EmailSettings = Field(default_factory=EmailSettings)
    consultation: ConsultationSettings = Field(default_factory=ConsultationSettings)


@lru_cache
def get_settings() -> Settings:
    return Settings()

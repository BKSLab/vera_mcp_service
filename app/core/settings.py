from functools import lru_cache

from pydantic import Field, SecretStr
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

    phoenix_otlp_endpoint: str = 'http://localhost:6006/v1/traces'


class Settings(BaseSettings):
    """Агрегатор всех доменных настроек проекта."""

    app: AppSettings = Field(default_factory=AppSettings)
    rag: RagClientSettings = Field(default_factory=RagClientSettings)
    observability: ObservabilitySettings = Field(default_factory=ObservabilitySettings)


@lru_cache
def get_settings() -> Settings:
    return Settings()

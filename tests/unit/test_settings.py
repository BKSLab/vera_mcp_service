from app.core.settings import Settings


def test_settings_load_flat_process_environment_without_email_collision(
    monkeypatch,
):
    values = {
        'RAG_SERVICE_URL': 'http://localhost:9/api/v1',
        'RAG_SERVICE_API_KEY': 'test-rag-key',
        'LLM_API_KEY': 'test-llm-key',
        'LLM_API_URL': 'http://localhost:9/api/v1',
        'CONSULTATION_FORMATTING_LLM_MODEL': 'test-formatting-model',
        'EMAIL': 'ci@example.com',
        'HOST_NAME': 'localhost',
        'PORT': '465',
        'APPLICATION_KEY': 'test-application-key',
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)

    settings = Settings()

    assert str(settings.email.email) == 'ci@example.com'
    assert settings.email.host_name == 'localhost'
    assert settings.email.port == 465
    assert settings.llm.consultation_formatting_llm_model == (
        'test-formatting-model'
    )
    assert settings.llm.llm_temperature == 0.1
    assert settings.email.smtp_max_attempts == 3
    assert settings.consultation.consultation_pdf_variant == 'pdf/ua-1'

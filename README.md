# vera_mcp_service

MCP Tools Server — инструментальный слой между Agent Service и конкретными
сервисами проекта «Работа для всех». Принимает вызовы по MCP-протоколу,
выполняет узкие бизнес-процессы и возвращает типизированный результат. Не
оркестрирует диалог и не хранит состояние сессии. Для формирования документов
может использовать собственный узкий LLM-процесс: структурирование уже готовой
консультации без изменения её смысла.

## Роль в системе

Последний из трёх сервисов архитектуры ассистента (`AGENT_VERA_ARCHITECTURE.md`): **Agent Service** (`vera_agent_service`, оркестратор, production-ready) → **MCP Tools Server** (этот репозиторий) → **RAG Service** (`vera_rag_service`, семантический поиск по базе знаний, production-ready). Оба соседних контракта уже зафиксированы кодом по обе стороны — этот сервис реализует тонкую прослойку по готовому ТЗ, а не проектирует контракт с нуля.

Сервис предоставляет два инструмента:

- `vera_rag_kb` — поиск по базе знаний Vera RAG;
- `send_consultation_email` — структурирование готовой консультации,
  формирование доступного PDF и отправка по email.

История базовой реализации находится в `MCP_SERVICE_PLAN.md`, реализация
консультации — в `CONSULTATION_EMAIL_TOOL_PLAN.md`.

## Как это работает

1. **Приём вызова** — `FastMCP` (`mcp.server.fastmcp`), транспорт `streamable-http`, работает автономно (`mcp.run(transport="streamable-http")`) — без FastAPI, по образцу проверенного на масштабе in-house проекта `tools-mcp` (см. план, раздел 0.1). Agent Service подключается через `MultiServerMCPClient` на `/mcp`.
2. **Инструмент `vera_rag_kb`** (`app/tools/vera_rag_kb.py`) — тонкий адаптер: валидация непустого `query` через Pydantic-схему MCP, затем вызов `RagClient.search()`. Роль пользователя в поисковый контракт не входит: RAG получает запрос без `audience` и ищет по всему корпусу. При сбое RAG Service исключение всплывает как есть: Agent Service (`handle_tool_errors=False`) ждёт именно исключение MCP-уровня, не `dict` с полем ошибки.
3. **Инструмент `send_consultation_email`** (`app/tools/send_consultation_email.py`) — тонкая MCP-граница над `ConsultationDeliveryService`. Email валидируется внутри тела тула, поэтому ошибка возвращается словарём, а не `ToolError`.
4. **Подготовка консультации** — общий `LlmClient` получает исходный текст как данные, возвращает `PreparedConsultation`, Jinja подставляет структуру в фирменный HTML-бланк, WeasyPrint формирует tagged PDF/UA с Unicode-текстом. Прикладных ограничений длины текста и `max_completion_tokens` нет.
5. **Отправка** — `SmtpClient` собирает `multipart/alternative` с PDF-вложением и выполняет только внутренние ограниченные ретраи временных SMTP-сбоев. Один `Message-ID` сохраняется на всех попытках. PDF существует только в памяти.
6. **Реестр тулов** (`app/tools/__init__.py::register_all_tools`) — единая точка регистрации, покрытая meta-тестом.
7. **Клиент RAG Service** (`app/clients/rag_client.py`) — `POST /api/v1/search` с `X-API-Key`, без собственного слоя ретраев.
8. **`GET /health`** проверяет RAG. Платные LLM-запросы и SMTP-login из health-check не выполняются.
9. **Наблюдаемость** — OpenTelemetry → общий Arize Phoenix project. Spans содержат длины, размеры и outcomes, но не текст консультации, email, PDF или секреты.

## Стек

`mcp` (`FastMCP`, streamable-http) · `httpx` · `pydantic` /
`pydantic-settings` · `Jinja2` · `WeasyPrint` · `aiosmtplib` · OpenTelemetry →
Arize Phoenix · Docker Compose. FastAPI сервису не нужен.

## Контракты

Подробности, JSON-примеры и обоснования — `MCP_SERVICE_PLAN.md`, раздел 3.

| Контракт | Кто использует | Кратко |
|---|---|---|
| Тул `vera_rag_kb` (MCP, streamable-http) | Agent Service → этот сервис | `vera_rag_kb(query: str) -> {"chunks": [...]}` — пустой список `chunks` валиден («нет ответа»), не ошибка. При сбое — исключение MCP-уровня, не `dict` с полем ошибки |
| Тул `send_consultation_email` | Agent Service → этот сервис | `send_consultation_email(consultation_text: str, email: str) -> dict`. Успех: `status`, нормализованный `email`, `document_name`, `message`. Предусмотренная ошибка: `status="error"`, стабильные `code` и `message` |
| `POST /api/v1/search` | Этот сервис → RAG Service | `{"query", "top_k"}` → `{"chunks": [...]}`, заголовок `X-API-Key`. `audience` намеренно не передаётся, поэтому RAG ищет по всему корпусу; его собственная опциональная поддержка фильтра остаётся доступной для будущих сценариев |
| OpenAI-compatible Chat Completions | Этот сервис → LLM API | Базовый `LLM_API_URL` дополняется `/chat/completions`; structured output валидируется через `PreparedConsultation` |
| SMTP TLS | Этот сервис → почтовый сервер | Отправка `EmailMessage` с plain/html телом и `application/pdf` вложением; подтверждённые бизнес-сбои возвращаются словарём |
| `GET /health` | Оркестратор/мониторинг | `{"status": "ok", "rag_service": "ok"\|"unreachable"}` — код ответа всегда `200` |

## Запуск локально

```bash
cp .env.example .env
# заполнить .env — RAG, LLM и SMTP-реквизиты

docker compose up -d --build
```

| Сервис | Адрес |
|---|---|
| MCP Tools Server (streamable-http) | `http://localhost:9000/mcp` |
| `GET /health` | `http://localhost:9000/health` |

Общий Phoenix (трейсы) — поднимается из `vera_agent_service/docker-compose.yml` (`http://localhost:6006`), не из этого репозитория (план, Этап 8.3 — единственный общий инстанс на все три сервиса).

### Роль MCP в распределённом trace

MCP сохраняет продуктовую границу между Agent и retrieval:

```text
tool.vera_rag_kb               vera_agent_service
└── mcp.execute.vera_rag_kb    vera_mcp_service
    └── rag.search             vera_rag_service

tool.send_consultation_email
└── mcp.execute.send_consultation_email
    ├── consultation.format
    ├── consultation.pdf.render
    └── consultation.email.send
```

Все сервисы должны использовать одинаковый `PHOENIX_PROJECT_NAME`, но одного
общего Phoenix недостаточно: дерево связывается динамической W3C propagation на
обоих сетевых переходах. Span MCP содержит только технические атрибуты и длину
query, без текста запроса или чанков. При завершении процесса общий HTTP-клиент
закрывается, затем выполняются `force_flush` и shutdown tracing.

Локально без Docker (venv):

Перед запуском переключить endpoint-блок в `.env`: закомментировать активные
production-адреса и раскомментировать строки из секции `Local endpoints`.

```bash
python -m venv venv
venv\Scripts\activate                # Windows; source venv/bin/activate — Linux/macOS
pip install -r requirements-dev.txt

python -m app.main
```

### Совместный запуск с Agent Service/RAG Service

Общая внешняя Docker-сеть больше не используется. Все сервисы развёртываются
на production-хосте `91.218.115.104` и обращаются друг к другу через его
опубликованные порты: Agent → MCP — `http://91.218.115.104:9000/mcp`,
MCP → RAG — `http://91.218.115.104:8002`, MCP → Phoenix —
`http://91.218.115.104:6006/v1/traces`.

В `.env` активна секция `Production endpoints`; секция `Local endpoints`
предназначена только для запуска `python -m app.main` непосредственно на хосте.

## Тестирование

```bash
pytest tests/                # юнит + интеграционные, без внешней инфраструктуры
ruff check .                 # линтер
```

Интеграционные тесты поднимают настоящий `FastMCP`-сервер на свободном порту
и подключаются настоящим `MultiServerMCPClient`. Реальные LLM/SMTP в
автоматических тестах не вызываются. Локальный SMTP contract-тест отправляет
настоящее MIME-письмо через loopback TCP-сокет без внешней почты. Text-layer
тест WeasyPrint запускается, когда в системе доступен Pango; в Windows без
Pango он пропускается, а перед production должен быть выполнен в
Linux-контейнере.

## Документация

- [`MCP_SERVICE_PLAN.md`](MCP_SERVICE_PLAN.md) — план реализации по этапам, зафиксированные технические решения, контракты, находки, конвенции для будущих тулов, соответствие WBS
- [`CONSULTATION_EMAIL_TOOL_PLAN.md`](CONSULTATION_EMAIL_TOOL_PLAN.md) — контракт и устройство отправки PDF-консультации
- [`LLM_CLIENT_REFERENCE.md`](LLM_CLIENT_REFERENCE.md) — эталон общего OpenAI-compatible LLM-клиента
- [`AGENT_VERA_ARCHITECTURE.md`](AGENT_VERA_ARCHITECTURE.md) — исходная архитектурная концепция трёх сервисов
- [`FASTAPI_PATTERNS.md`](FASTAPI_PATTERNS.md) — эталонные паттерны кода проекта (частично применимо — этот сервис не на FastAPI, см. план, раздел 0.1)

### Как добавить новый тул

1. Новый файл `app/tools/<name>.py` — `<name>(...)` + `register_<name>(mcp, ...)` с развёрнутым `description` (перечислением каждого параметра текстом — влияет на выбор тула LLM).
2. Одна строка в `app/tools/__init__.py::register_all_tools`.
3. Классифицировать тул как read-only или мутирующий. Для мутирующего тула явно определить внутренние/внешние retries и риск дубликатов до реализации.
4. Бизнес-процесс размещать в `app/services/`, оставляя MCP-функцию тонкой.
5. Юнит-тесты тула, обновить `tests/unit/tools/test_registry.py` (новое имя — в ожидаемый набор).
6. Ручной OpenTelemetry span, если тул делает внешний вызов помимо уже покрытых.

## Чеклист перед production-развёртыванием

Локально и функционально всё готово и проверено (см. «Статус» ниже) — но это не значит готовность к реальному прод-деплою. По приоритету, сверху вниз:

**P0 — открытых блокеров нет:**
- Провижининг БД RAG исправлен; production health-check RAG возвращает `database=ok`.
- Реальный `RAG_SERVICE_API_KEY` задан в локальном production `.env` (само значение не коммитится). Плейсхолдер в `.env.example` оставлен намеренно как безопасный шаблон.
- LLM и SMTP-реквизиты находятся в игнорируемом `.env`; перед деплоем проверить их тестовым вызовом без пользовательских данных.

**P1 — инфраструктура сейчас dev-уровня, не прод:**
- Нет Nginx/TLS перед сервисом — MCP-эндпоинт сейчас голый HTTP на `9000`.
- Лимит памяти в `docker-compose.yml` (`512M`) — placeholder-значение, не проверено нагрузочным тестированием.
- Agent Service должен отключить внешний retry для `send_consultation_email` и назначить отдельный увеличенный timeout.

**P2 — не верифицировано мной фактическим прогоном:**
- CI (`.github/workflows/ci.yml`) написан и локально согласован с реальной инфраструктурой, но реальный прогон на GitHub Actions не проверялся — нет доступа к Actions из этой среды. Проверить на первом push/PR.
- Единое дерево трейса через все три сервиса в живом Phoenix требует проверки после production-деплоя Agent Service.
- Полный путь `Agent → MCP → RAG` с реальным контентом требует отдельного E2E-прогона после production-деплоя Agent Service.
- PDF/UA необходимо проверить валидатором и вручную скринридером в Linux-контейнере; локальная Windows-среда не содержит Pango.
- Реальную SMTP-доставку проверить в безопасный тестовый ящик.

**Семантика доставки:** SMTP обеспечивает at-least-once, а не строгую
exactly-once-гарантию. Повторы находятся только внутри `SmtpClient`, один
`Message-ID` переиспользуется; долговременный outbox в текущую версию не входит.

## Статус

Реализованы `vera_rag_kb` и `send_consultation_email`. Unit- и
contract/integration-тесты не требуют внешней инфраструктуры; `ruff check .`
должен оставаться чистым. Для консультации остаются эксплуатационные проверки:
реальный LLM structured output, PDF/UA в контейнере, SMTP в тестовый ящик и
сквозной Agent Service без внешнего retry.

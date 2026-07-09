# vera_mcp_service

MCP Tools Server — инструментальный слой между Agent Service и конкретными сервисами данных (проект «Работа для всех»): принимает вызов инструмента по MCP-протоколу, вызывает нужный внешний сервис и возвращает результат. Не оркестрирует диалог, не хранит состояние сессии, не знает о LLM — общается с Agent Service только через MCP-протокол.

## Роль в системе

Последний из трёх сервисов архитектуры ассистента (`AGENT_VERA_ARCHITECTURE.md`): **Agent Service** (`vera_agent_service`, оркестратор, production-ready) → **MCP Tools Server** (этот репозиторий) → **RAG Service** (`vera_rag_service`, семантический поиск по базе знаний, production-ready). Оба соседних контракта уже зафиксированы кодом по обе стороны — этот сервис реализует тонкую прослойку по готовому ТЗ, а не проектирует контракт с нуля.

Итерация 1: единственный инструмент — `kb_search` (поиск по базе знаний), доступен без авторизации. Полная история решений, находок и статус по этапам — `MCP_SERVICE_PLAN.md`.

## Как это работает

1. **Приём вызова** — `FastMCP` (`mcp.server.fastmcp`), транспорт `streamable-http`, работает автономно (`mcp.run(transport="streamable-http")`) — без FastAPI, по образцу проверенного на масштабе in-house проекта `tools-mcp` (см. план, раздел 0.1). Agent Service подключается через `MultiServerMCPClient` на `/mcp`.
2. **Инструмент `kb_search`** (`app/tools/kb_search.py`) — тонкий адаптер: валидация аргументов (`query` непустой, `audience` — `Literal['seeker', 'employer', 'both']`) через Pydantic-схему MCP, затем вызов `RagClient.search()`. Никакого `try/except` вокруг вызова — при сбое RAG Service исключение всплывает как есть: Agent Service (`handle_tool_errors=False`) ждёт именно исключение MCP-уровня, не `dict` с полем ошибки.
3. **Реестр тулов** (`app/tools/__init__.py::register_all_tools`) — единственное место, которое трогают при добавлении нового инструмента (итерация 2: `get_user_favorites`, `search_vacancies`, `find_similar_vacancies`). Сопровождается meta-тестом (`tests/unit/tools/test_registry.py`), ловящим забытую регистрацию/дублирование имени.
4. **Клиент RAG Service** (`app/clients/rag_client.py`) — `POST /api/v1/search` с `X-API-Key`. Без собственного слоя ретраев: Agent Service уже ретраит вызов тула целиком, RAG Service ретраит embedding/reranker внутри себя — ещё один слой был бы «ретраями в квадрате».
5. **`GET /health`** — реестр проверок (`app/health.py::HealthRegistry`), тот же принцип расширяемости, что и у реестра тулов. Код ответа всегда `200`, недоступность RAG Service отражается только в теле (`{"status": "ok", "rag_service": "unreachable"}`) — сервис не падает из-за деградации соседа.
6. **Наблюдаемость** — OpenTelemetry (без автоинструментации — `mcp`/`FastMCP` ею не покрываются) → Arize Phoenix. Ручные spans на границах: `mcp.tool_call` (атрибут `mcp.tool_name`) вокруг вызова тула, вложенный `rag.search` вокруг вызова RAG Service.

## Стек

`mcp` (официальный MCP SDK, `FastMCP`, streamable-http) · `httpx` (клиент к RAG Service) · `pydantic`/`pydantic-settings` · OpenTelemetry → Arize Phoenix (наблюдаемость) · Docker Compose. Без FastAPI/`hypercorn` — сервис сам поднимает встроенный ASGI-сервер, `fastapi` этому сервису не нужен (план, раздел 0.1).

## Контракты

Подробности, JSON-примеры и обоснования — `MCP_SERVICE_PLAN.md`, раздел 3.

| Контракт | Кто использует | Кратко |
|---|---|---|
| Тул `kb_search` (MCP, streamable-http) | Agent Service → этот сервис | `kb_search(query: str, audience: "seeker"\|"employer"\|"both" = "both") -> {"chunks": [...]}` — пустой список `chunks` валиден («нет ответа»), не ошибка. При сбое — исключение MCP-уровня, не `dict` с полем ошибки |
| `POST /api/v1/search` | Этот сервис → RAG Service | `{"query", "audience", "top_k"}` → `{"chunks": [...]}`, заголовок `X-API-Key`. Формат ответа дословно совпадает с тем, что ожидает Agent Service от `kb_search` — прозрачный проброс, без трансформации полей |
| `GET /health` | Оркестратор/мониторинг | `{"status": "ok", "rag_service": "ok"\|"unreachable"}` — код ответа всегда `200` |

## Запуск локально

```bash
cp .env.example .env
# заполнить .env — минимум RAG_SERVICE_URL, RAG_SERVICE_API_KEY

docker compose up -d --build
```

| Сервис | Адрес |
|---|---|
| MCP Tools Server (streamable-http) | `http://localhost:9000/mcp` |
| `GET /health` | `http://localhost:9000/health` |

Общий Phoenix (трейсы) — поднимается из `vera_agent_service/docker-compose.yml` (`http://localhost:6006`), не из этого репозитория (план, Этап 8.3 — единственный общий инстанс на все три сервиса).

Локально без Docker (venv):

```bash
python -m venv venv
venv\Scripts\activate                # Windows; source venv/bin/activate — Linux/macOS
pip install -r requirements-dev.txt

python -m app.main
```

### Совместный запуск с Agent Service/RAG Service

Для реальной сквозной интеграции трём сервисам нужна общая Docker-сеть (создаётся один раз, не управляется ни одним отдельным `docker-compose.yml`):

```bash
docker network create vera_network
```

После этого `docker compose up -d` в каждом из трёх репозиториев (`vera_agent_service`, `vera_mcp_service`, `vera_rag_service`) — сервисы видят друг друга по имени контейнера (`vera_mcp_service`, `vera_rag_service`, `vera_agent_phoenix`). Подробности и подтверждённые находки — `MCP_SERVICE_PLAN.md`, Этап 8.

## Тестирование

```bash
pytest tests/                # юнит + интеграционные, без внешней инфраструктуры
ruff check .                 # линтер
```

Интеграционные тесты (`tests/integration/`) поднимают настоящий `FastMCP`-сервер этого сервиса на свободном локальном порту (`uvicorn`, в процессе теста) и подключаются настоящим `MultiServerMCPClient` — не требуют внешней инфраструктуры. RAG Service в тестах не поднимается — обращения к нему замоканы (`httpx.MockTransport`) или застаблены собственным HTTP-сервером теста (`tests/integration/test_rag_contract.py`).

## Документация

- [`MCP_SERVICE_PLAN.md`](MCP_SERVICE_PLAN.md) — план реализации по этапам, зафиксированные технические решения, контракты, находки, конвенции для будущих тулов, соответствие WBS
- [`AGENT_VERA_ARCHITECTURE.md`](AGENT_VERA_ARCHITECTURE.md) — исходная архитектурная концепция трёх сервисов
- [`FASTAPI_PATTERNS.md`](FASTAPI_PATTERNS.md) — эталонные паттерны кода проекта (частично применимо — этот сервис не на FastAPI, см. план, раздел 0.1)

### Как добавить новый тул

1. Новый файл `app/tools/<name>.py` — `<name>(...)` + `register_<name>(mcp, ...)` с развёрнутым `description` (перечислением каждого параметра текстом — влияет на выбор тула LLM).
2. Одна строка в `app/tools/__init__.py::register_all_tools`.
3. Классифицировать: read-only (безопасно ретраить как есть) или мутирующий тул (см. открытый вопрос про идемпотентность, `MCP_SERVICE_PLAN.md`, раздел 0.3/6 — retry-политика для тулов с побочными эффектами не решена, решить **до** реализации).
4. Если нужна логика поверх одного клиента — `app/services/<name>_service.py` (слой ещё не заведён, появляется по факту первой необходимости), не раздувать файл тула.
5. Юнит-тесты тула, обновить `tests/unit/tools/test_registry.py` (новое имя — в ожидаемый набор).
6. Ручной OpenTelemetry span, если тул делает внешний вызов помимо уже покрытых.

## Чеклист перед production-развёртыванием

Локально и функционально всё готово и проверено (см. «Статус» ниже) — но это не значит готовность к реальному прод-деплою. По приоритету, сверху вниз:

**P0 — блокирует полностью:**
- **Провижининг БД в `vera_rag_service` не работает в текущем окружении** (`InvalidCatalogNameError: database "vera_rag_service" does not exist`) — реальный `kb_search` с живыми данными невозможен, пока это не починено в том репозитории. MCP-протокол, контракт и сетевая связность подтверждены рабочими независимо от этого блокера (`MCP_SERVICE_PLAN.md`, Этап 8/9) — сам этот сервис не является причиной.
- **`RAG_SERVICE_API_KEY` — плейсхолдер** в `.env`/`.env.example` обоих репозиториев — нужно реальное значение.

**P1 — инфраструктура сейчас dev-уровня, не прод:**
- Нет Nginx/TLS перед сервисом — MCP-эндпоинт сейчас голый HTTP на `9000`.
- Лимит памяти в `docker-compose.yml` (`512M`) — placeholder-значение, не проверено нагрузочным тестированием.

**P2 — не верифицировано мной фактическим прогоном:**
- CI (`.github/workflows/ci.yml`) написан и локально согласован с реальной инфраструктурой, но реальный прогон на GitHub Actions не проверялся — нет доступа к Actions из этой среды. Проверить на первом push/PR.
- Единое дерево трейса через все три сервиса в живом Phoenix — топология сети подтверждена, реальный сквозной трейс через RabbitMQ/Agent/MCP/RAG — нет (упирается в P0).
- Полный путь `Agent → MCP → RAG` с реальным контентом никогда не прогонялся целиком — упирается в P0.

**Осознанно не блокер:** per-tool retry-политика для будущих мутирующих тулов итерации 3+ не решена — не актуально, пока единственный тул (`kb_search`) read-only и идемпотентен; уже задокументировано в `MCP_SERVICE_PLAN.md` (раздел 0.3, риски) как задача, которую нужно решить до итерации 3+, не забытый пробел.

## Статус

Итерация 1 реализована (`MCP_SERVICE_PLAN.md`, этапы 0–8, 10) и проверена: 41/41 тест (юнит + интеграционные, дважды подряд стабильно), `ruff check .` чист, production-образ собран и поднят (`docker inspect` → `healthy`), реальная сетевая интеграция с `vera_agent_service`/`vera_rag_service` подтверждена (`agent_service` реально резолвит и согласовывает MCP-протокол с этим сервисом по имени контейнера). Этап 9 (сквозной E2E с реальными данными) заблокирован внешней причиной — провижинингом БД в `vera_rag_service`, не в этом сервисе. Перед реальным публичным запуском — см. чеклист выше, начиная с P0.

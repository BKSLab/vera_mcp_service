# MCP Tools Server — План реализации

> **Статус реализации:** 🔶 Итерация 1 реализована. Этапы 0–8 и 10 выполнены; Этап 9 (сквозной E2E с реальными данными) заблокирован внешней причиной — провижининг БД в `vera_rag_service`, не связано с этим планом (см. Этап 9, раздел 4 рисков). Дата плана: 2026-07-09.
>
> **Как отчитываться:** каждая подзадача — отдельный чек-бокс `- [ ]` с номером `N.M`. Отмечаем `[x]` только когда подзадача реально сделана и (если применимо) покрыта тестом. По мере работы статус каждого этапа меняется на ✅/🔶/⏳ прямо в заголовке этапа, а под чек-листом добавляется абзац "Фактически сделано" с находками — по образцу `vera_agent_service/AGENT_SERVICE_PLAN.md` и `vera_rag_service/RAG_SERVICE_PLAN.md`. Каждый этап закрывается только при выполнении своего "Definition of Done".
>
> **Обновление контракта, 2026-07-18:** MCP-инструмент и связанные внутренние имена изменены с `kb_search` на `vera_rag_kb` (`vera_rag_kb.py`, `register_vera_rag_kb`). Прежнее имя в исторических записях ниже следует читать как `vera_rag_kb`. Agent Service требует синхронного обновления резолвинга инструмента.
>
> **Итерация:** 1 — единственный инструмент `vera_rag_kb`, доступ без авторизации. Инструменты итерации 2 (`get_user_favorites`, `search_vacancies`, `find_similar_vacancies`) и далее — вне рамок этого плана, но структура сервиса (раздел 1, 0.1) спроектирована так, чтобы их добавление не требовало переработки.
>
> **Источники:**
> - `AGENT_VERA_ARCHITECTURE.md` (этот репозиторий) — архитектурная концепция, роль MCP Tools Server в трёхсервисной системе.
> - `FASTAPI_PATTERNS.md` (этот репозиторий) — эталонные паттерны кода для проектов на FastAPI (частично применимо — см. раздел 0.1, этот сервис не на FastAPI).
> - `D:\BKS.Lab\python\my_projects\vera_agent_service\AGENT_SERVICE_PLAN.md`, раздел 3.3, и код `app/clients/mcp_client.py` + `tests/fixtures/mock_mcp_server.py` — **зафиксированный контракт**, который этот сервис обязан реализовать со стороны Agent Service. Agent Service (итерация 1) полностью реализован и протестирован, production-образ собран и здоров — единственный оставшийся блокер его реального запуска: этот сервис не существует. **Транспорт уже переведён на `streamable_http`** (раздел 0.2, выполнено 2026-07-09) — код и тесты Agent Service обновлены и зелены.
> - `D:\BKS.Lab\python\my_projects\vera_rag_service\README.md`, раздел `POST /api/v1/search` — **зафиксированный контракт** RAG Service, к которому этот сервис обращается. RAG Service — production-ready по результатам техревью (`RAG_CODE_AUDIT_REPORT.md`).
> - `D:\biocard\projects\tools-mcp` — соседний in-house проект (другой продукт, Bitrix24-интеграция), тоже на `mcp.server.fastmcp.FastMCP`, но в проде на ~60 тулах. Источник паттернов для роста числа инструментов (раздел 0.1, 0.3) — не источник контракта (тот зафиксирован Agent Service/RAG Service), а источник проверенных архитектурных решений на масштабе, которого у нас пока нет, но будет.
> - `D:\BKS.Lab\python\my_projects\site_work_for_everyone\AGENT_VERA_WBS.txt` — разделы 1.2.3, 2.9.1–2.9.2, 3.3, 3.4.
>
> **Ключевое отличие от планов соседних сервисов:** там контракты по одну (иногда обе) стороны ещё проектировались. Здесь — обе стороны уже реализованы и зафиксированы работающим кодом, не только текстом в markdown. Задача этого плана инженерная (реализовать тонкую прослойку по готовому ТЗ), а не архитектурная — почти все решения раздела 0.1 не выбираются, а **считываются** из `mcp_client.py`/`mock_mcp_server.py`/README RAG-сервиса. Единственное исключение — транспорт и внутренняя структура сервиса (раздел 0.1/0.2), где решение принято в этом плане осознанно и требует синхронной правки на стороне Agent Service.

---

## 0. Назначение и рамки сервиса

MCP Tools Server — инструментальный слой между Agent Service и конкретными сервисами данных (`AGENT_VERA_ARCHITECTURE.md`, раздел "Три сервиса"). Сам не оркестрирует диалог, не хранит состояние сессии, не знает о LLM — принимает вызов инструмента по MCP-протоколу, вызывает нужный внутренний/внешний сервис и возвращает результат. Расширяется добавлением новых файлов в `tools/` — Agent Service узнаёт о новом инструменте через сам MCP-протокол, без изменений на своей стороне.

**В рамках этого плана:**
- Инструмент `kb_search(query, audience="both") -> dict`, проксирующий `POST /api/v1/search` в RAG Service.
- MCP-сервер на `FastMCP` (streamable-http, standalone — раздел 0.1), с явным реестром регистрации тулов, спроектированным под добавление новых инструментов без переработки композиции.
- HTTP-клиент к RAG Service с корректной обработкой ошибок (см. раздел 0.1 — критично для совместимости с Agent Service).
- `GET /health` — через `FastMCP.custom_route`.
- Наблюдаемость: ручные OpenTelemetry-спаны → Arize Phoenix.
- Docker-образ, тесты, документация контрактов.
- Обязательные правки на стороне `vera_agent_service` для перехода на `streamable_http` (раздел 0.2) — без них Этап 3 (верификация протокола) невозможен.
- Сетевая интеграция с двумя уже существующими сервисами для реального сквозного прогона (этапы 9–10) — этого не сделал ни один из трёх планов до сих пор (раздел 4).

**Вне рамок этого плана:**
- Сами **Agent Service** и **RAG Service** — уже реализованы, здесь только клиенты/контракты к ним и точечные правки транспорта (раздел 0.2).
- Сами инструменты итерации 2 (`get_user_favorites`, `search_vacancies`, `find_similar_vacancies`) и их источники данных — только структура, которая их примет.
- Контроль доступа по `user_id` — в архитектурном документе описан для тулов итерации 2; `kb_search` в итерации 1 доступен всем, включая незалогиненных (подтверждено и на стороне Agent Service — там такой логики тоже нет, раздел 0.1).
- Загрузка полного корпуса документов в RAG Service — внешняя зависимость, отслеживается в `vera_rag_service` (раздел 4).
- DI-фреймворк (`dishka`/аналоги) — сознательно не вводится на этой итерации (раздел 0.1).

---

## 0.1. Зафиксированные технические решения

| Решение | Выбор | Причина |
|---|---|---|
| Фреймворк MCP | `mcp.server.fastmcp.FastMCP`, официальный SDK | `AGENT_VERA_ARCHITECTURE.md`, WBS 3.3.2 — согласовано всеми тремя сторонами; тот же пакет использует и `tools-mcp` в проде |
| Версия `mcp` SDK | `mcp==1.28.1` | Реально резолвится в `venv` Agent Service через `langchain-mcp-adapters==0.3.0` (проверено `pip show mcp`) — фиксируем ту же версию во избежание протокольных рассинхронизаций |
| **Транспорт** | **`streamable-http`, не SSE** (решение чата, 2026-07-09) | Streamable HTTP — актуальный рекомендуемый транспорт в спецификации MCP (пришёл на смену чистому HTTP+SSE); так уже сделано в `tools-mcp`, и клиент, и сервер. SSE в `mcp` SDK продолжает работать, но не развивается как основной. Цена решения: код Agent Service (`mcp_client.py`, `mock_mcp_server.py`) сейчас жёстко на SSE — требует правки, см. раздел 0.2 |
| **Способ запуска — без FastAPI** | `FastMCP` работает автономно: `mcp.run(transport="streamable-http")`, `GET /health` — через `@mcp.custom_route("/health", methods=["GET"])`, а не отдельное FastAPI-приложение с `app.mount(...)` | По образцу `D:\biocard\projects\tools-mcp` — тот же `mcp.server.fastmcp.FastMCP` работает в проде на ~60 тулах без FastAPI вообще. `mcp.mount("/mcp", mcp.streamable_http_app())` на пустом `FastAPI()` даёт неудобный путь `/mcp/mcp` (у `streamable_http_app()` собственный маршрут уже на `/mcp`, см. `streamable_http_path` в конструкторе `FastMCP`) — мёртвый слой ради путаницы в пути. `custom_route` закрывает единственную причину, ради которой FastAPI был нужен (health-эндпоинт) |
| `stateless_http=True` | Передаётся в конструктор `FastMCP` | Сервис полностью stateless (следующая строка) — опция отключает управление MCP-сессиями там, где оно не нужно, каждый вызов `kb_search` независим |
| Порт | Контейнер слушает **8000** (`host`/`port` конструктора `FastMCP`, тот же внутренний порт, что у `vera_agent_service`/`vera_rag_service` — единообразие `Dockerfile`/`EXPOSE`/`HEALTHCHECK`), хост-порт в `docker-compose.yml` — **9000** | `MCP_SERVER_URL` в `vera_agent_service` (после правки раздела 0.2) — `http://localhost:9000/mcp`. Разные хост-порты у всех трёх сервисов (8000/8010/9000) — уже используемый в проекте паттерн |
| **Регистрация тулов — реестр, не единственный декоратор в `main.py`** | Один файл на тул в `tools/`, каждый экспортирует `register_<name>(mcp: FastMCP) -> None`; явный список вызовов собирается в одном месте (`tools/__init__.py::register_all_tools`) | По образцу `tools-mcp` (`infrastructure/mcp/handlers/*.py` + `presentation/mcp.py::create_mcp_server`) — там же паттерн доказан на ~60 тулах. У нас на итерацию 1 всего один тул, но количество будет расти (итерация 2 — ещё три, итерация 3+ — тулы платформы, `AGENT_VERA_ARCHITECTURE.md`, раздел "Итерации") — реестр с первого дня устраняет единственную точку роста в `main.py`, которая иначе разрослась бы в нечитаемую портянку декораторов |
| **Явные описания тулов** | `description=` в `mcp.tool(...)`/эквиваленте — с перечислением каждого параметра текстом, не полагаться только на docstring | По образцу `tools-mcp/infrastructure/mcp/handlers/task_create.py` — на выбор нужного тула и заполнение его аргументов LLM сильнее влияет explicit `description`, чем короткий docstring; это становится критично, когда тулов у агента не один, а несколько (итерация 2+) и модели нужно среди них выбирать |
| **DI-фреймворк (`dishka`/аналоги)** | **Не вводится** на этой итерации | `tools-mcp` использует `dishka` оправданно: ~60 тулов, десяток внешних интеграций (Bitrix24, RabbitMQ, Redis, Postgres, email, GitLab...). У нас на итерацию 1 один тул и один внешний клиент (RAG Service); `pydantic-settings` + module-level singleton клиента (управляется `lifespan`, как в `FASTAPI_PATTERNS.md`, раздел 6) достаточно и не требует лишней абстракции. Пересмотреть, если к итерации 3+ число интеграций реально вырастет на порядок |
| Имя и сигнатура тула | `kb_search(query: str, audience: str = "both") -> dict` — **должны совпасть буквально** | Agent Service резолвит тул по имени `kb_search` из `client.get_tools()` (`mcp_client.py:167`); локальный `build_kb_search_tool_proxy` на его стороне уже забинден на эту сигнатуру для схемы аргументов LLM |
| Формат ответа `kb_search` | Идентичен `POST /api/v1/search` из `vera_rag_service` — `{"chunks": [...]}`, пустой список — валидный ответ ("нет ответа"), не ошибка | Зафиксировано на обеих сторонах дословно (`mcp_client.py`, `mock_mcp_server.py`, RAG `README.md`) — `kb_search` реализуется как прозрачный проброс, без трансформации полей |
| Обработка сбоя RAG Service | `kb_search` **бросает исключение**, не возвращает `dict` с полем ошибки | Agent Service создаёт `MultiServerMCPClient(handle_tool_errors=False)` именно для того, чтобы ошибка тула приходила как исключение MCP-уровня (`mcp_client.py:35-39`). Если наш тул поймает ошибку и вернёт `{"error": "..."}`, агент воспримет это как валидный (пустой) результат и не задействует свою логику деградации ("поиск временно недоступен"). Этот же принцип независимо подтверждён и в `tools-mcp` (`task_create.py`: `except CreateTaskError: logger.error(...); raise`) |
| Ретраи к RAG Service | Нет собственного слоя ретраев, только таймаут на попытку | Agent Service уже ретраит вызов тула целиком (`MCP_CALL_RETRIES`, экспоненциальный backoff, `mcp_client.py:59-90`), RAG Service уже ретраит embedding/reranker внутри себя. Собственный слой ретраев здесь — "ретраи в квадрате", риск утроить худший случай задержки |
| Состояние | Полностью stateless | Нет диалога, нет сессий — каждый вызов `kb_search` независим. Следствие: воркеров/процессов может быть `>1` без ограничений, характерных для Agent Service (там — in-process SSE-очередь) |
| Авторизация тула `kb_search` | Без авторизации | Итерация 1 архитектуры — доступен всем, включая незалогиненных; на стороне Agent Service такой фильтрации тоже пока нет |
| `topic`/`category` параметры RAG Service | **Не входят** в сигнатуру `kb_search` итерации 1 | RAG API их уже поддерживает, но контракт со стороны Agent Service зафиксирован как `(query, audience)` — добавление опциональных параметров с дефолтами технически не сломало бы обратную совместимость, но выходит за рамки согласованного ТЗ. Задел на итерацию 2 (раздел 6) |
| Дополнительные тулы (`get_user_favorites` и т.д.) | Вне рамок этого плана | Итерация 2 архитектуры, отдельный трек — структура (реестр `tools/`) уже готова их принять |

---

## 0.2. Обязательные правки в `vera_agent_service` ✅ Выполнено (2026-07-09)

Переход на `streamable-http` — решение этого плана, но контракт зафиксирован кодом по обе стороны (см. источники выше), поэтому правка нужна и там. Без неё Этап 3 (верификация протокола) и Этап 10 (E2E) этого плана невозможны. Внесено сразу, не отложено — чтобы Agent Service и MCP Tools Server разрабатывались дальше на общем транспорте.

- [x] 0.2.1 `app/clients/mcp_client.py:40-50` (`get_mcp_client`) — `'transport': 'sse'` → `'transport': 'streamable_http'`
- [x] 0.2.2 `.env.example` и `.env` — `MCP_SERVER_URL=http://localhost:9000/mcp/sse` → `http://localhost:9000/mcp`
- [x] 0.2.3 `tests/fixtures/mock_mcp_server.py` — переписан на standalone `FastMCP.streamable_http_app()` (без обёртки в `FastAPI` — маршрут уже на `/mcp` сам по себе, лишний `app.mount()` не нужен)
- [x] 0.2.4 `_parse_tool_result` (`mcp_client.py:173-189`) — подтверждено прогоном: формат результата тула действительно не зависит от транспорта, код не потребовал изменений
- [x] 0.2.5 Полный прогон `pytest tests/` в `vera_agent_service` после правок

**Definition of Done:** `vera_agent_service` подключается к тестовому MCP-серверу этого репозитория через `streamable_http` и все существующие тесты Agent Service по-прежнему зелёные. ✅ Подтверждено: 20/20 тестов, затронутых MCP-клиентом и графом (`tests/unit/clients/test_mcp_client.py`, `tests/integration/test_mcp_client.py`, `tests/integration/test_graph.py`), зелёные, `ruff check .` чист. Оставшиеся 9 упавших тестов всего прогона (`test_consumer.py`, `test_consumer_sse_pipeline.py`, `test_main.py`, `test_redis_checkpointer.py`) падают из-за недоступных локально RabbitMQ/Redis (контейнеры не подняты в этой сессии) — не связаны с переходом на streamable-http.

**Находка, подтверждённая эмпирически (важно для Этапа 3 и Этапа 3.1 этого плана):** проблема `sse_starlette.sse.AppStatus.should_exit` (раньше считалась специфичной для SSE-транспорта) **воспроизводится и на streamable-http** — `mcp` SDK использует `sse_starlette.EventSourceResponse` внутри `mcp/server/streamable_http.py` для потоковых ответов сервера, независимо от того, что сам транспорт называется иначе. Без сброса `AppStatus.should_exit = False` в `finally` второй мок-сервер, поднятый в одном процессе, вешает клиента на `initialize` ("peer closed connection without sending complete message body"). Обход сохранён в `mock_mcp_server.py` — при реализации собственного тестового сервера в этом репозитории (Этап 3) нужен тот же обход.

---

## 0.3. Расширяемость — конвенции для будущих тулов (ревью 2026-07-09)

`kb_search` — прозрачный проброс без бизнес-логики. Итерация 2 (`get_user_favorites`, `search_vacancies`, `find_similar_vacancies`) и итерация 3+ (отклики, избранное, AI-матчинг) — это уже тулы с реальной логикой и, местами, с побочными эффектами. Ниже — решения и риски, которые дешевле зафиксировать сейчас, чем изобретать по одному при каждом новом тule.

| Вопрос | Решение/статус | Обоснование |
|---|---|---|
| Слоистость при появлении бизнес-логики | `tools/<name>.py` (тонкий MCP-адаптер: валидация аргументов + один вызов) → `services/<name>_service.py` (оркестрация нескольких клиентов, бизнес-правила — заводится, когда тулу нужно больше одного вызова/решения) → `clients/<external>.py` (один клиент на одну внешнюю систему) | Тот же принцип, что и `FASTAPI_PATTERNS.md` (endpoint→service→repository), просто применённый к тулам заранее, а не изобретённый заново в итерации 2. `services/` не заводится сейчас (раздел 1) — только форма зафиксирована для единообразия, когда понадобится |
| Обработка ошибок — общий принцип для **любого** будущего тула | Исключение наружу, никогда `dict` с полем ошибки — не частное решение для `kb_search`/RAG (раздел 0.1), а общее правило для всех тулов этого сервиса, независимо от внешней системы | Одна семантика ошибки на весь MCP-протокол сервиса — агент обрабатывает недоступность любого тула одним и тем же путём деградации |
| **Идемпотентность и ретраи мутирующих тулов** | **Не решено, требует решения до итерации 3+.** Agent Service ретраит **любой** вызов тула вслепую до `MCP_CALL_RETRIES` раз при любой ошибке/таймауте (`call_tool_with_retry`, единая политика на весь клиент). Для `kb_search` (чтение) это безопасно. Для будущих мутирующих тулов (отклик на вакансию, избранное) слепой ретрай после таймаута — риск задвоить операцию, которая на самом деле уже выполнилась | Нет ни в одном из трёх планов механизма пометить тул как «небезопасно ретраить» — потребует либо per-tool retry policy на стороне Agent Service, либо idempotency-key в аргументах мутирующих тулов. Зафиксировано как риск (раздел 4) и открытый вопрос (раздел 6) — решить до начала итерации 3+, не откладывать до первого инцидента |
| `GET /health` при росте числа внешних зависимостей | Строить сразу как маленький реестр (`register_health_check(name, check_fn)`), не как растущую цепочку `if` вокруг одного RAG-чека | Тот же принцип, что и реестр тулов (раздел 0.1) — при появлении Dadata/векторного поиска в итерации 2 добавление проверки не требует переписывать существующий код |
| Конфигурация новых интеграций | Один домен `*Settings` на одну внешнюю систему (`DadataSettings` и т.п.), не смешивать в один класс | Уже заложено в `FASTAPI_PATTERNS.md`, раздел 3 — явно фиксируем, чтобы не смешали при первом добавлении |
| Логирование и PII | Не логировать полный текст пользовательского запроса на уровне `INFO` в проде (логировать длину/хэш при необходимости диагностики, не содержание) | Сервис — консультант по правам людей с инвалидностью; запросы пользователей потенциально содержат чувствительные данные о здоровье/инвалидности. Дешевле решить на одном тule, чем на десяти с разным стилем логирования |
| Версионирование сигнатур тулов | Additive-параметры с дефолтами — безопасны без координации с Agent Service. Breaking-изменения существующей сигнатуры — новое имя тула или синхронный релиз с Agent Service | Agent Service резолвит тул по имени и локальной копии схемы аргументов (раздел 0.1) — молчаливое рассогласование схем не всплывёт сразу, а даст трудноуловимую ошибку заполнения аргументов у LLM |
| Порог пересмотра решения «без DI-фреймворка» (раздел 0.1) | Конкретный триггер вместо расплывчатого «на порядок»: пересмотреть, когда тулов станет ≥5-6 **с реальной оркестрацией** (не проброс) или когда появится первая зависимость, требующая per-request scoping (не process-lifetime singleton) | Расплывчатый критерий не даёт понять, когда именно возвращаться к вопросу — конкретное число фиксирует момент ревизии |
| Rate limit RAG Service (60 запросов/мин) на стороне клиента | Не реализовано, риск учтён (раздел 4) | Сейчас не критично (один тул, один инстанс), но `find_similar_vacancies`/`search_vacancies` тоже могут дёргать RAG или смежные сервисы — совокупная нагрузка растёт быстрее числа тулов. Клиентский rate-limiter/circuit breaker — не в рамках итерации 1, но не забыть при добавлении второго тула, дёргающего RAG |

**Чеклист для добавления нового тула** (переносится в `README.md`, этап 10.1, как проверяемый список, не только описание):
1. Новый файл `tools/<name>.py` — `_<name>(...)` + `register_<name>(mcp)` с развёрнутым `description` (раздел 0.1).
2. Одна строка в `tools/__init__.py::register_all_tools`.
3. Классификация: read-only (безопасно ретраить как есть) или мутирующий (см. строку про идемпотентность выше — решить retry-политику **до** реализации, не после).
4. Если нужна логика поверх одного клиента — `services/<name>_service.py` (см. слоистость выше), не раздувать `tools/<name>.py`.
5. Юнит-тесты тула/сервиса, обновление meta-теста реестра (Этап 6 — новое имя тула должно попасть в список ожидаемых).
6. Ручной/observability span, если тул делает внешний вызов помимо уже покрытых.

---

## 1. Структура проекта

```
vera_mcp_service/
├── app/
│   ├── main.py                  # создаёт FastMCP("vera-tools", host=..., port=..., stateless_http=True,
│   │                             #   lifespan=...), register_all_tools(mcp), custom_route("/health"),
│   │                             #   mcp.run(transport="streamable-http")
│   ├── core/
│   │   ├── settings.py          # Pydantic Settings: AppSettings, RagClientSettings, ObservabilitySettings
│   │   └── config_logger.py     # logging.config.fileConfig, по образцу FASTAPI_PATTERNS.md, раздел 4
│   ├── tools/
│   │   ├── __init__.py          # register_all_tools(mcp: FastMCP) -> None — явный список вызовов,
│   │   │                        #   единственное место, которое трогают при добавлении нового тула
│   │   └── vera_rag_kb.py       # vera_rag_kb(...) + register_vera_rag_kb(mcp) — итерация 1
│   ├── clients/
│   │   └── rag_client.py        # httpx.AsyncClient, X-API-Key, POST /api/v1/search
│   │                             #   (один файл на внешнюю систему — итерация 2 добавит dadata_client.py и т.п.)
│   ├── exceptions/
│   │   └── rag.py                # RagUnavailableError — единое исключение для вызывающего кода
│   │                             #   (один файл на клиента, зеркалит clients/ — раздел 0.3)
│   └── observability/
│       └── tracing.py            # OpenTelemetry TracerProvider + OTLP/HTTP экспортёр в Phoenix
├── tests/
│   ├── unit/                     # rag_client на httpx.MockTransport, валидация аргументов тула
│   └── integration/               # реальный streamable-http сервер этого сервиса + настоящий MultiServerMCPClient
├── Dockerfile                     # адаптация текущей копии vera_agent_service (этап 0)
├── docker-compose.yml              # mcp_service (+ опционально phoenix)
├── entrypoint.sh                    # python -m app.main — без hypercorn/ASGI-сервера снаружи (раздел 0.1)
├── requirements.txt / requirements-dev.txt
├── pyproject.toml                    # ruff
├── logging.ini
└── MCP_SERVICE_PLAN.md                # этот файл
```

**Отклонение от `FASTAPI_PATTERNS.md`:** сервис не на FastAPI (раздел 0.1) — слои `db/`, `repositories/`, `services/`, `admin/`, `background_tasks/`, `api/v1/endpoints/`, `dependencies/` не заводятся. Роль "сервисного" слоя выполняет сам инструмент (`tools/vera_rag_kb.py`) поверх клиента (`clients/rag_client.py`). Отдельный `services/`-слой между `tools/` и `clients/` сознательно не заводится для одного прозрачного проксирующего тула — станет оправданным, когда у первого тула итерации 2 появится реальная бизнес-логика поверх клиента (например, `search_vacancies` с нормализацией локации через Dadata — это уже не голый проброс).

---

## 2. Этапы реализации

### Этап 0 — Скаффолд проекта и адаптация инфраструктуры ✅ Выполнено (2026-07-09)

Цель: репозиторий перестаёт быть копией `vera_agent_service` (RabbitMQ/Redis/checkpointer/hypercorn, которых здесь не должно быть вообще) и становится рабочим каркасом MCP Tools Server.

- [x] 0.1 `core/settings.py` — Pydantic Settings, домены `AppSettings` (`mcp_service_host`, `mcp_service_port`), `RagClientSettings` (`rag_service_url`, `rag_service_api_key: SecretStr`, `rag_search_timeout_seconds`, `rag_search_top_k`), `ObservabilitySettings` (`phoenix_otlp_endpoint`) — по образцу `FASTAPI_PATTERNS.md`, раздел 3
- [x] 0.2 `core/config_logger.py` + `logging.ini` — логгер `vera_mcp_service` вместо `vera_agent_service`, `aio_pika`-логгер убран (оставлены `httpx`/`httpcore` — используются `rag_client.py`, Этап 1)
- [x] 0.3 `.env.example`/`.env` — переписаны с нуля, без `RABBITMQ_*`/`REDIS_*`/`HYPERCORN_WORKERS`
- [x] 0.4 `docker-compose.yml` — `rabbitmq`/`redis` убраны, один сервис `mcp_service` (контейнер `vera_mcp_service`), порт `9000:8000`, `env_file: .env`, лимит памяти `512M`, опциональный локальный `phoenix` (порты 6006/4317 — известный конфликт с соседними repo при одновременном локальном запуске, задокументирован комментарием в файле и в разделе 6, вопрос 1)
- [x] 0.5 `Dockerfile`/`entrypoint.sh` — упоминания checkpointer/RabbitMQ-consumer/hypercorn убраны; команда запуска — `python -m app.main`; `HEALTHCHECK` на `http://localhost:8000/health`
- [x] 0.6 `requirements.txt`/`requirements-dev.txt` — созданы. Runtime: `mcp==1.28.1`, `httpx==0.28.1`, `pydantic==2.13.4`, `pydantic-settings==2.14.2`, `opentelemetry-api/sdk/exporter-otlp-proto-http==1.43.0` (версии синхронизированы с `vera_agent_service/requirements.txt`). Без `fastapi`/`hypercorn` (раздел 0.1). Dev: `langchain-mcp-adapters==0.3.0` (интеграционные тесты Этапа 3), `pytest==9.1.1`, `pytest-asyncio==1.4.0`, `pytest-cov==7.1.0`, `ruff==0.15.20`
- [x] 0.7 `pyproject.toml` — уже был настроен верно (`ruff`, `known-first-party = ["app"]`), правок не потребовалось. Добавлен `pytest.ini` (`asyncio_mode = auto`) — не было в исходном чек-листе, но нужен для `pytest-asyncio`, обнаружено по ходу

**Definition of Done:** `pip install -r requirements-dev.txt` в чистом `venv` — без конфликтов (72 пакета, конфликтов версий не найдено). `ruff check .` — чист. `docker build .` — образ собирается без build-тулчейна (без `gcc`), тестовый образ собран и удалён после проверки. **Уточнение к исходной формулировке DoD:** проверялась именно сборка образа (`docker build`), не полный `docker compose up -d mcp_service` — `app/main.py` появляется только в Этапе 4, поэтому реальный старт контейнера с проверкой `/health` откладывается туда же и в Этап 7 (Docker-образ и деплой), по тому же принципу, что и в `vera_agent_service` (там Этап 0 тоже проверял только `pip install`/`ruff`/сборку инфраструктурных сервисов, не самого приложения).

**Ссылки:** `D:\BKS.Lab\python\my_projects\vera_agent_service\docker-compose.yml`, `entrypoint.sh`, `Dockerfile`, `.env.example` — источник, от которого была склонирована инфраструктура этого репозитория.

---

### Этап 1 — Клиент RAG Service ✅ Выполнено (2026-07-09)

- [x] 1.1 `clients/rag_client.py` — `POST {RAG_SERVICE_URL}/api/v1/search`, заголовок `X-API-Key: {RAG_SERVICE_API_KEY}`, JSON-тело `{"query", "audience", "top_k"}`, таймаут `RAG_SEARCH_TIMEOUT_SECONDS`. `httpx.AsyncClient` принимается через конструктор, не создаётся внутри — клиент будет управляться `lifespan` в `main.py` (этап 4)
- [x] 1.2 `exceptions/rag.py` — `RagUnavailableError`: единое исключение для сетевой ошибки, таймаута, `5xx`, `429` и неожиданного формата ответа (пустой/невалидный JSON, отсутствие поля `chunks`)
- [x] 1.3 Юнит-тесты `rag_client.py` на `httpx.MockTransport`: успех с непустыми чанками, успех с пустым `chunks: []` (не ошибка), корректная передача заголовка `X-API-Key` и тела запроса, таймаут → `RagUnavailableError`, сетевая ошибка соединения → `RagUnavailableError`, `500`/`429` → `RagUnavailableError`, невалидный JSON → `RagUnavailableError`, отсутствие поля `chunks` → `RagUnavailableError`

**Definition of Done:** `search(...)` против мок-транспорта возвращает `dict` при успехе (включая пустой `chunks`) и бросает `RagUnavailableError` на любом из перечисленных сбоев — без исключений, которые не являются `RagUnavailableError`. ✅ 9/9 тестов зелёные, `ruff check .` чист.

**Ссылки:** `vera_rag_service/README.md`, раздел `POST /api/v1/search` — точный контракт запроса/ответа, коды ошибок `422`/`500`/`429`.

**Фактически сделано, с одним отклонением от исходного текста плана:** `rag_client.py` — не голая функция `search(...)`, а класс `RagClient(httpx_client, settings)` с методом `search()` — по образцу `FASTAPI_PATTERNS.md`, раздел 13 ("Клиенты внешних API": "один клиент = один внешний сервис, принимает готовый `httpx.AsyncClient` через конструктор"), тот же паттерн, что и в примере `ExternalApiClient` из раздела 18 (тесты клиентов). Класс, а не модульная функция — чище тестируется (свежий инстанс на тест с собственным `httpx.MockTransport`, без module-level состояния) и не требует протаскивать `httpx.AsyncClient`/`settings` через каждый вызов вручную. Второе отклонение — логирование: вместо полного текста запроса на `INFO` логируется только `query_length` (раздел 0.3, решение про PII — реализовано сразу, не отложено).

---

### Этап 2 — Инструмент `kb_search` и реестр тулов ✅ Выполнено (2026-07-09)

- [x] 2.1 `tools/vera_rag_kb.py` — `register_vera_rag_kb(mcp, rag_client, top_k)`, регистрирует замыкание `vera_rag_kb(query, audience="both")` через `mcp.add_tool(...)` с развёрнутым `description`
- [x] 2.2 `tools/__init__.py::register_all_tools(mcp, rag_client, rag_top_k)`
- [x] 2.3 Никакого `try/except` вокруг `rag_client.search()` внутри `kb_search` — исключение всплывает как есть
- [x] 2.4 Валидация аргументов: `audience: Literal['seeker', 'employer', 'both']` (открытый вопрос 4 — решение принято: `Literal` не ломает резолвинг тула на стороне Agent Service, проверено юнит-тестами); `query: Annotated[str, Field(min_length=1)]` — пустая строка отклоняется до вызова `rag_client`. Оба варианта подтверждены эмпирически через `mcp.call_tool(...)`: невалидные аргументы бросают `ToolError` до входа в тело функции, `rag_client.search` не вызывается

**Definition of Done:** прямой вызов `kb_search` через `mcp.call_tool('kb_search', {...})` возвращает ожидаемый результат при успехе `rag_client`; при `RagUnavailableError` из `rag_client` исключение долетает до вызывающего кода (`ToolError`), не превращается в `dict` с полем ошибки; `register_all_tools(mcp, ...)` регистрирует ровно один тул с именем `kb_search`. ✅ 21/21 тестов проекта зелёные (9 из Этапа 1 + 12 новых), `ruff check .` чист.

**Ссылки:** `AGENT_VERA_ARCHITECTURE.md`, раздел "MCP Tools Server — внутреннее устройство"; `vera_agent_service/app/clients/mcp_client.py:158-170`; `D:\biocard\projects\tools-mcp\src\infrastructure\mcp\handlers\task_create.py` — образец паттерна `register_<tool>` и развёрнутого `description`.

**Фактически сделано, с отклонениями от исходного текста плана и находками:**

- **`register_vera_rag_kb` принимает `rag_client`/`top_k` параметрами, не читает их из модуля/глобальных настроек** — явная передача зависимостей вместо скрытого module-level состояния (согласуется с решением раздела 0.1 "без DI-фреймворка": зависимости передаются явно через конструктор/параметры, а не через контейнер). `RagClient` создаётся в `main.py` (Этап 4) и передаётся в `register_all_tools`.
- **Находка (важна для Этапа 3):** `mcp.call_tool(name, arguments)` — высокоуровневый in-process API `FastMCP`, отличный от реального MCP/JSON-RPC пути через `MultiServerMCPClient`. При невалидных аргументах или исключении внутри функции тула он оборачивает ошибку в `mcp.server.fastmcp.exceptions.ToolError`, не позволяя ей проскочить как "успешный" результат — то есть **на этом уровне** контракт "исключение, не dict" уже подтверждён. Но это не тождественно реальному протокольному пути (content-блоки + `handle_tool_errors=False` на клиенте) — тот отдельно верифицируется в Этапе 3 против настоящего `MultiServerMCPClient`, не заменяется этой находкой.
- **Успешный `mcp.call_tool(...)` возвращает `list[TextContent]`, не `dict` напрямую** — подтверждено эмпирически (`result[0].text` — JSON-строка). Согласуется с тем, что уже задокументировано на стороне Agent Service (`_parse_tool_result`, `mcp_client.py:173-189`) — то же поведение протокола, не специфика нашей реализации.
- **Тесты реестра (`tests/unit/tools/test_registry.py`)** — на этом этапе уже написан минимальный вариант meta-теста, который в плане был запланирован на Этап 6.4 (проверка набора имён тулов, отсутствия дублей, непустых описаний). Написан сразу, а не отложен — дешевле поддерживать по ходу добавления тулов, чем добавлять задним числом. Этап 6.4 при выполнении сверяется с этим файлом, а не переписывает его заново.

---

### Этап 3 — Верификация протокола ошибок MCP (интеграционный) ✅ Выполнено (2026-07-09)

Не "фича", а проверка того, что уже зафиксировано в разделе 0.1 — отдельным этапом, потому что именно здесь на практике чаще всего расходятся ожидания и реальность MCP SDK (это уже случилось один раз на стороне Agent Service — находка про `handle_tool_errors`, `mcp_client.py:184-189`). Требовал завершённого раздела 0.2 (выполнен) — Agent Service умеет говорить `streamable_http`.

- [x] 3.1 `tests/integration/test_protocol_compatibility.py` — поднимает настоящий `FastMCP` этого сервиса (`register_all_tools`, `streamable_http_app()`, реальный `uvicorn` на свободном порту), подключается настоящим `MultiServerMCPClient(handle_tool_errors=False, transport="streamable_http")` из `langchain-mcp-adapters==0.3.0`:
  - успешный вызов `kb_search` возвращает список content-блоков `[{"type": "text", "text": "<json>", "id": "..."}]`, не сырой `dict` — подтверждено эмпирически, формат действительно не зависит от транспорта (раздел 0.2.4)
  - недоступный RAG Service (`httpx.ConnectError` в моке транспорта `RagClient`) → вызов тула **бросает** `langchain_mcp_adapters.tools._MCPToolExecutionError`, не возвращает `{}`/`{"chunks": []}`
- [x] 3.2 Тот же тест на `500` от RAG Service — тот же результат: `_MCPToolExecutionError`, не `dict`

**Definition of Done:** оба сценария 3.1/3.2 подтверждены против настоящего MCP/streamable-http протокола. ✅ 4/4 новых интеграционных теста зелёные (дважды подряд, стабильно), 25/25 тестов проекта в целом, `ruff check .` чист.

**Ссылки:** `vera_agent_service/tests/fixtures/mock_mcp_server.py` — референс сценария (не копировался, но повторена именно такая проверка); `mcp_client.py:173-189` (`_parse_tool_result`).

**Фактически сделано, с находками:**

- **RAG Service не поднимается отдельным реальным HTTP-сервером** — `RagClient` в тесте получает `httpx.AsyncClient` с `httpx.MockTransport` (тот же приём, что и в Этапе 1), реальный сетевой путь есть только на MCP-уровне (клиент ↔ наш `uvicorn`-сервер). Это осознанно уже: цель Этапа 3 — верифицировать MCP-протокол, а не RAG HTTP — RAG-часть уже покрыта Этапом 1 изолированно.
- **Подтверждена находка раздела 0.2.4 буквально**: успешный ответ `kb_search` — не `dict`, а `[{"type": "text", "text": "<json>", "id": "lc_..."}]`, идентично тому, что задокументировано в `_parse_tool_result` на стороне Agent Service. Тест использует собственный мини-парсер (`_parse_tool_result` в тесте), логика которого специально зеркалит агентскую — не копия кода, но копия проверки, как и предписывала ссылка в исходном плане.
- **Точный тип исключения** — `langchain_mcp_adapters.tools._MCPToolExecutionError` (приватный класс модуля, `ruff` B017 запретил голый `except`/`pytest.raises(Exception)` — пришлось найти конкретный тип эмпирически, не гадать). Тот же тип, что ловит `call_tool_with_retry` на стороне Agent Service (`mcp_client.py`, широкий `except Exception` там — осознанное решение, задокументированное в его коде: тип ошибки не имеет значения для решения "поиск недоступен").
- **Повторный прогон интеграционных тестов дважды подряд** — стабильно зелёный, обход `AppStatus.should_exit` (раздел 0.2) работает и для собственного сервера этого репозитория, не только для мока Agent Service.

---

### Этап 4 — `main.py`: сборка приложения и `GET /health` ✅ Выполнено (2026-07-09)

- [x] 4.1 `main.py` — `mcp = FastMCP("vera-tools", host=..., port=..., stateless_http=True)`, `register_all_tools(mcp, rag_client, ...)`, `@mcp.custom_route("/health", methods=["GET"])`, `mcp.run(transport="streamable-http")` в `run()`/`__main__`. Код ответа `/health` всегда `200`
- [x] 4.2 Никакого жёсткого startup-чека доступности RAG Service — подтверждено тестом (сервис отвечает на `/health` и на MCP-вызовы независимо от доступности RAG)
- [x] 4.3 `HealthRegistry` (`app/health.py`) — реестр проверок по образцу `register_all_tools` (раздел 0.3): `.register(name, check)`/`.run() -> dict[str, str]`, не один захардкоженный RAG-чек. На этой итерации зарегистрирована одна проверка (`rag_service` → `RagClient.check_health()`), интерфейс уже рассчитан на вторую без переписывания существующей
- [x] 4.4 Юнит-тесты: `RagClient.check_health()` — `200` → `True`, `503`/сетевая ошибка → `False`, запрашивается ожидаемый путь (`tests/unit/clients/test_rag_client.py`); `HealthRegistry` изолированно — `ok`/`unreachable`/множественные независимые проверки/исключение в проверке трактуется как `unreachable`, не падает (`tests/unit/test_health.py`)

**Definition of Done:** приложение стартует и отвечает на `GET /health` и на MCP-вызовы (`/mcp`) даже при заведомо недоступном `RAG_SERVICE_URL`. ✅ 35/35 тестов проекта зелёные (дважды подряд), `ruff check .` чист. Интеграционный тест (`tests/integration/test_main.py`) поднимает настоящий `app.main.mcp` и проверяет `GET /health` (`200`, поле `rag_service` — `ok`/`unreachable`, окружение-зависимо) и что `kb_search` виден настоящему `MultiServerMCPClient`.

**Фактически сделано, с существенным отклонением от исходного текста плана и находкой:**

- **`lifespan=app_lifespan` у `FastMCP` — не использован, вопреки исходному наброску плана.** Находка: у `mcp.server.fastmcp.FastMCP` параметр `lifespan` — это контекст **низкоуровневого MCP-сервера**, привязанный к жизненному циклу MCP-**сессии** через `StreamableHTTPSessionManager`, а не ASGI-старт всего процесса (в отличие от `lifespan` в FastAPI/Starlette). Подтверждено вручную: тулы, зарегистрированные внутри такого lifespan, не гарантированно видны до первого реального MCP-запроса — `GET /health` (обычный Starlette `custom_route`, вне MCP-сессии) отдавал ответ раньше, чем lifespan успевал выполниться. Решение: `httpx.AsyncClient()`, `RagClient`, `register_all_tools(...)` и `HealthRegistry` собираются **синхронно на уровне модуля** — конструктор `httpx.AsyncClient()` не требует запущенного event loop, только `.get()/.post()/.aclose()` асинхронны, поэтому это безопасно. Явного закрытия `httpx_client` при остановке процесса нет — некритично (сокеты освобождает ОС при завершении процесса), эксплицитный `lifespan` для этого не подходит по только что описанной причине.
- **Вторая находка:** `app.main.mcp` — процессный синглтон (как и в реальном деплое, `mcp.run()` вызывается ровно один раз за процесс), и `FastMCP.streamable_http_app()`/`StreamableHTTPSessionManager.run()` можно вызвать только один раз за время жизни инстанса. Интеграционный тест поэтому — один тест с одним запуском сервера на оба сценария (health + список тулов), не два отдельных теста с общей fixture (module-scoped async fixture у `pytest-asyncio` конфликтовала с function-scoped event loop этого проекта и подвешивала прогон — `pytest.ini` не настраивает `asyncio_default_fixture_loop_scope`, менять его ради одного теста не оправдано).

---

### Этап 5 — Observability (Phoenix) ✅ Выполнено (2026-07-09)

Из `AGENT_VERA_ARCHITECTURE.md`, раздел "Observability" — этому сервису отведены **ручные** spans на каждый вызов тула (в отличие от Agent Service, где основной объём покрывает автоинструментация `LangChainInstrumentor` — здесь такой автоинструментации нет, `mcp`/`FastMCP` ею не покрываются).

- [x] 5.1 `observability/tracing.py` — `TracerProvider` + OTLP/HTTP экспортёр в `PHOENIX_OTLP_ENDPOINT`, `configure_tracing()`/`get_tracer()`/`reset_for_tests()` — по образцу `vera_agent_service/app/observability/tracing.py` (без `openinference`/`LangChainInstrumentor` — не нужны, здесь нет LangChain)
- [x] 5.2 Span `mcp.tool_call` (атрибут `mcp.tool_name=vera_rag_kb`) вокруг вызова тула (`app/tools/vera_rag_kb.py`), вложенный span `rag.search` вокруг тела `RagClient.search()` (`app/clients/rag_client.py`) — дерево подтверждено тестом: `mcp.tool_call: vera_rag_kb └── rag.search`
- [x] 5.3 Юнит-тесты (`tests/unit/observability/test_tracing.py`): оба спана создаются с ожидаемыми именами/атрибутом, вложенность подтверждена сравнением `rag_search_span.parent.span_id == tool_call_span.context.span_id`

**Definition of Done:** тестовый вызов `kb_search` виден span-деревом `mcp.tool_call → rag.search` с корректной вложенностью. ✅ 38/38 тестов проекта зелёные (дважды подряд), `ruff check .` чист. Реальная проверка в живом Phoenix (аналог того, что делал Agent Service на своём Этапе 9) — не выполнялась в этой сессии, локальный Phoenix не поднимался; структура спанов верифицирована через `InMemorySpanExporter`, что и было целью этого этапа.

**Ссылки:** `AGENT_VERA_ARCHITECTURE.md`, раздел "Observability — логирование и оценка агента".

**Фактически сделано, с находкой, важной для порядка инициализации:**

- **`configure_tracing()` вызывается не на уровне модуля `main.py`, а внутри `run()`.** Находка: при полном прогоне тестов (`pytest tests/`, не по одному файлу) `tests/integration/test_main.py` импортирует `app.main`, который на уровне модуля вызывал `configure_tracing(settings.observability)` — это настоящий `TracerProvider` с `OTLPSpanExporter` на `http://localhost:6006/v1/traces`. Он **выигрывал гонку** за `set_tracer_provider()` (можно вызвать только один раз за процесс — та же находка, что и в `vera_agent_service`) раньше, чем модуль `tests/unit/observability/test_tracing.py` успевал вызвать свой `reset_for_tests(_exporter)` — из-за порядка сбора тестов `pytest`. В результате все три теста этого этапа падали **только при полном прогоне**, по отдельности — проходили (тот же класс проблемы, что уже находился в `vera_agent_service`, Этап 5, только там причиной был `AppStatus.should_exit`, здесь — `set_tracer_provider()`). Фоновый эффект был виден и по логам: `BatchSpanProcessor` реального провайдера пытался экспортировать спаны в недоступный Phoenix и логировал ошибки таймаута экспорта. Исправлено переносом `configure_tracing()` в `run()` — импорт `app.main` (в том числе тестами) больше не имеет побочного эффекта настройки глобального OTel-состояния. Безопасно: `trace.get_tracer()`, уже вызванный при импорте `app/tools/kb_search.py`/`app/clients/rag_client.py`, возвращает прокси, резолвящий актуальный провайдер в момент создания span'а, не в момент вызова `get_tracer()`.

---

### Этап 6 — Тестирование (сводный этап) ✅ Выполнено (2026-07-09)

- [x] 6.1 Консолидация юнит-тестов, написанных по ходу этапов 1–2, 4–5 — покрытие подтверждено (41 тест всего)
- [x] 6.2 Интеграционные тесты этапа 3 — совместимость протокола ошибок против настоящего MCP/streamable-http
- [x] 6.3 Contract-тест (`tests/integration/test_rag_contract.py`) — `RagClient` против настоящего HTTP-стаба (`Starlette`+`uvicorn`, не `httpx.MockTransport`), реализующего схему `POST /api/v1/search`: happy-path и отказ по неверному `X-API-Key`. **Известное ограничение зафиксировано в docstring файла:** стаб не синхронизирован автоматически со схемой `vera_rag_service` — расхождение реального контракта обнаружится не раньше Этапа 9
- [x] 6.4 **Meta-тест реестра тулов** — уже был написан на Этапе 2 (`tests/unit/tools/test_registry.py`): набор имён, отсутствие дублей, непустые описания
- [x] 6.5 Тест на конкурентные вызовы (`test_concurrent_kb_search_calls_do_not_share_state`) — 20 параллельных `kb_search` через `asyncio.gather` с разными query, каждый вызов получает свой, а не чужой результат
- [x] 6.6 `ruff check .` — чист
- [x] 6.7 CI (`.github/workflows/ci.yml`) — `pip install -r requirements-dev.txt` → `ruff check .` → `pytest tests/ -v`. Без `services:` (в отличие от `vera_agent_service` — нет RabbitMQ/Redis); `RAG_SERVICE_URL`/`RAG_SERVICE_API_KEY` — плейсхолдеры, нужны только чтобы `Settings()` сконструировался при импорте

**Definition of Done:** полный прогон `pytest tests/` зелёный локально. ✅ 41/41 тестов, дважды подряд стабильно, `ruff check .` чист. CI не верифицирован реальным прогоном на GitHub Actions в этой сессии (нет доступа к CI-инфраструктуре) — тот же известный статус, что и у `vera_agent_service`/`vera_rag_service` при первой сдаче их CI, требует проверки на первом реальном push/PR.

---

### Этап 7 — Docker-образ и деплой ✅ Выполнено (2026-07-09)

- [x] 7.1 Финальная сверка `Dockerfile`/`docker-compose.yml`/`entrypoint.sh` — без build-тулчейна, непривилегированный пользователь, `HEALTHCHECK` на `/health`
- [x] 7.2 `docker compose up -d --build mcp_service` — реальная сборка и запуск. `docker logs`: чистый старт (`StreamableHTTP session manager started` → `Application startup complete` → `Uvicorn running on http://0.0.0.0:8000`). `docker inspect` → `State.Health.Status: healthy`
- [x] 7.3 `curl http://localhost:9000/health` (хост-порт) → `200`, `{"status":"ok","rag_service":"unreachable"}`

**Definition of Done:** `docker compose up -d --build` поднимает `mcp_service`, `GET /health` отвечает `200`. ✅ Подтверждено полным реальным циклом, включая `MultiServerMCPClient` из хоста против контейнера — контейнер остановлен и удалён после проверки (`docker compose down`), не оставлен висеть.

**Фактически сделано, с находкой (тот же класс проблемы, что уже был у `vera_agent_service` на его Этапе 11):**

Вызов `kb_search` через настоящий `MultiServerMCPClient` с хоста против запущенного контейнера (`http://localhost:9000/mcp`) корректно долетел до тула и вернул `_MCPToolExecutionError`, но с текстом `HTTP 404: Not Found`, а не ожидаемой сетевой ошибкой — потому что `.env` содержит `RAG_SERVICE_URL=http://localhost:8000`, что верно для локальной разработки на хосте, но не для контейнера: внутри Docker-сети `localhost` означает сам контейнер `mcp_service`, который слушает `:8000` сам себя (MCP-эндпоинт), а не RAG Service. Запрос `POST /api/v1/search` попал на собственный сервис контейнера, который такого маршрута не имеет — отсюда `404`. Ожидаемо и не является багом: `docker-compose.yml` этого репозитория сознательно не переопределяет `RAG_SERVICE_URL` (RAG Service — не часть этого compose-файла), правильный адрес (`http://vera_rag_service:8000` в общей сети) — задача Этапа 8, не этого. Контракт при этом отработал верно в любом случае: **любой** сбой RAG Service (включая "постучались не туда") превращается в `RagUnavailableError` → `_MCPToolExecutionError` на стороне клиента, не в тихий пустой результат — то, ради чего строился весь контракт (раздел 0.1).

---

### Этап 8 — Сетевая интеграция трёх сервисов ✅ Выполнено (2026-07-09)

**Пробел, не закрытый ни одним из трёх планов до сих пор.** Каждый репозиторий поднимает полностью изолированный `docker-compose.yml` — свою Docker-сеть по умолчанию, доступ к соседям только через `localhost` и опубликованные наружу порты хоста. Для реального совместного прогона (этап 9) сервисам нужно видеть друг друга по именам контейнеров:

- [x] 8.1 Внешняя Docker-сеть `vera_network` (`docker network create vera_network`), подключены все три `docker-compose.yml` (`mcp_service`, `agent_service`+`phoenix`, `rag_service` — каждый `networks: [default, vera_network]`, `vera_network: {external: true}`)
- [x] 8.2 `MCP_SERVER_URL` в `vera_agent_service` → `http://vera_mcp_service:8000/mcp`; `RAG_SERVICE_URL` в этом сервисе → `http://vera_rag_service:8000`. `.env.example` каждого репозитория сохраняет `localhost`-значения по умолчанию для локальной разработки одного репозитория — оверрайд только в `environment:` каждого `docker-compose.yml`
- [x] 8.3 Дублирование Phoenix решено: единственный общий инстанс — `vera_agent_phoenix` (в `vera_agent_service/docker-compose.yml`, теперь тоже на `vera_network`). Собственный `phoenix`-сервис в `vera_mcp_service/docker-compose.yml` убран, `PHOENIX_OTLP_ENDPOINT` этого сервиса указывает на `http://vera_agent_phoenix:6006/v1/traces`. `vera_rag_service` Phoenix/observability вообще не подключён (не было и до этого этапа — вне рамок этого плана, отдельная задача для того репозитория)

**Definition of Done:** все три сервиса, поднятые каждый из своего `docker-compose.yml`, видят друг друга по имени контейнера в общей сети. ✅ Подтверждено реальным прогоном всех трёх стеков одновременно:
- `agent_service` ↔ `mcp_service` — полностью подтверждено: `GET /health` агента вернул `{"status":"ok","rabbitmq":"ok","redis":"ok","mcp":"ok"}`, в логах агента видно реальное согласование MCP-протокола (`Negotiated protocol version`) с `vera_mcp_service` по имени контейнера
- `mcp_service` ↔ `vera_agent_phoenix` — DNS резолвится (`socket.gethostbyname` из контейнера `mcp_service`)
- `mcp_service` ↔ `rag_service` — DNS резолвится (подтверждено эмпирически из контейнера `mcp_service`), но `vera_rag_service` не удержался в стабильном `Up`-состоянии дольше нескольких секунд за раз — не проблема сети, см. находку ниже
- Единое дерево трейса через все сервисы в живом Phoenix — не проверялось в этой сессии (требует реального запроса через RabbitMQ, это уже Этап 9), только топология сети

**Фактически сделано, с находками за рамками формального чек-листа плана (потребовались, чтобы вообще получить возможность верифицировать сеть):**

При реальном совместном запуске всех трёх стеков обнаружены три проблемы, не связанные с сетью как таковой, но блокировавшие саму возможность её проверить:

1. **`vera_agent_service` не поднялся с первой попытки** — RabbitMQ ещё не был готов принимать соединения в момент старта `agent_service` (race на старте нескольких контейнеров, `depends_on` в Compose без `condition: service_healthy` ждёт только запуск контейнера, не готовность порта). Не баг, устранено простым перезапуском `agent_service` после того как `rabbitmq` окончательно поднялся.
2. **`vera_rag_service` не запускался вообще** — `entrypoint.sh` падал с `$'\r': command not found`. Причина — `core.autocrlf=true` в Windows-git на этой машине конвертирует файл в CRLF при чекауте, хотя закоммиченный блоб всегда был чистым LF. Исправлено добавлением `.gitattributes` (`*.sh text eol=lf`) в `vera_rag_service` — не трогает содержимое скрипта, чинит будущие чекауты на любой Windows-машине.
3. **После фикса №2 — `vera_rag_service` падал на подключении к Postgres/Qdrant** (`POSTGRES_HOST=localhost`/`QDRANT_URL=http://localhost:6333` из `.env` внутри контейнера резолвятся в сам контейнер `rag_service`, не в соседние `db`/`qdrant`) — тот же класс проблемы, что уже решён в `vera_agent_service` для `RABBITMQ_HOST`/`REDIS_HOST`. Исправлено таким же `environment:`-оверрайдом в `vera_rag_service/docker-compose.yml`. После этого дошло до нового, уже не сетевого и не Compose-уровневого сбоя (`InvalidCatalogNameError: database "vera_rag_service" does not exist` — провижининг БД/миграции) — это уже отдельная задача самого `vera_rag_service`, не в рамках этого плана; не стал разматывать дальше.

Все три находки — не про эту сеть или этот сервис, а про существовавшие раньше и никогда не проверявшиеся вместе допущения инфраструктуры `vera_agent_service`/`vera_rag_service`. Изменения закоммичены в обоих репозиториях (в `vera_agent_service` — запушено; в `vera_rag_service` — закоммичено локально, push не выполнен без отдельного подтверждения, см. итоговое сообщение в чате).

Все контейнеры остановлены и удалены после проверки (`docker compose down` во всех трёх репозиториях). Внешняя сеть `vera_network` оставлена — она предназначена жить дольше одного прогона.

---

### Этап 9 — Сквозной E2E-прогон 🔶 Заблокирован внешней причиной (2026-07-09)

Закрывает P0-блокер, зафиксированный в `vera_agent_service/README.md` ("полный путь Agent → MCP → RAG с реальным контентом никогда не прогонялся целиком").

- [ ] 9.1 Поднять все три сервиса вместе (этап 8), реальный запрос: клиент → RabbitMQ → Agent Service → этот MCP-сервер → RAG Service → ответ через SSE
- [ ] 9.2 Проверить на нескольких типовых вопросах из архитектурного документа ("квоты трудоустройство инвалидов" и т.п.) — с текущим содержимым RAG (сырой ТК РФ, полный корпус от эксперта ещё не загружен) результат будет технически корректным, но не обязательно полным по содержанию — это ограничение корпуса RAG Service, не этого сервиса и не Agent Service (см. риски, раздел 4)

**Definition of Done:** хотя бы один реальный вопрос проходит весь путь клиент → RabbitMQ → Agent Service → MCP Tools Server → RAG Service → SSE-ответ с источником, без ошибок на стыках. **Не достигнуто.**

**Блокер (решение — задокументировать и не разматывать дальше, зафиксировано в чате 2026-07-09):** `vera_rag_service` не поднимается до рабочего состояния даже после сетевых фиксов Этапа 8 — `asyncpg.exceptions.InvalidCatalogNameError: database "vera_rag_service" does not exist`. База данных не провижинится/миграции не создают её на чистом Postgres-контейнере в этом окружении. Это внутренняя проблема `vera_rag_service` (провижининг БД или порядок миграций), не имеющая отношения ни к MCP-протоколу, ни к сетевой интеграции, ни к контракту `kb_search` — все три уже подтверждены рабочими по отдельности (этапы 3, 7, 8). Чинить БД в чужом репозитории — вне рамок этого плана.

Что уже фактически подтверждено вместо полного E2E (совокупно закрывает большую часть содержательного риска Этапа 9):
- Контракт `kb_search` работает по-настоящему через MCP/streamable-http протокол (этап 3) и через реальный собранный Docker-образ этого сервиса (этап 7)
- `agent_service` реально видит и резолвит `mcp_service` по имени в общей сети, согласовывает MCP-протокол (этап 8)
- `mcp_service` реально резолвит `rag_service` по имени в общей сети (этап 8) — сетевой путь до RAG открыт, дальше блокирует уже не сеть

**Что остаётся не проверенным:** реальный `POST /api/v1/search` от `mcp_service` к живому, полностью рабочему `rag_service` с реальными данными; реальный сквозной путь через RabbitMQ и SSE от лица клиента. Требует отдельной задачи в `vera_rag_service` (провижининг БД) прежде чем этот этап можно будет закрыть по-настоящему.

---

### Этап 10 — Документация ✅ Выполнено (2026-07-09)

- [x] 10.1 `README.md` — назначение сервиса в системе, "как это работает" (6 шагов), стек, таблица контрактов, запуск локально (Docker и venv) и совместно с двумя другими сервисами (`vera_network`), тестирование, чеклист перед production (P0/P1/P2), статус. Инструкция "как добавить новый тул" — по образцу чеклиста раздела 0.3 этого плана
- [x] 10.2 Раздел 3 этого плана (Контракты) сверен с фактической реализацией — расхождений не найдено, менять не потребовалось

**Definition of Done:** документ, который можно передать без дополнительных устных пояснений — как `vera_agent_service/README.md` служит источником для Frontend-команды. ✅ `README.md` переписан полностью (был однострочный `# vera_mcp_service`), по структуре и глубине зеркалит `vera_agent_service/README.md`, честно отражает реальный статус, включая незакрытый блокер Этапа 9.

**Фактически сделано:** README также фиксирует найденную в Этапе 8 сетевую находку (`vera_network`, единый Phoenix у `vera_agent_service`) и блокер Этапа 9 (провижининг БД `vera_rag_service`) как P0-пункт чеклиста перед production — та же честная форма отчётности, что и в `vera_agent_service/README.md` ("Этот сервис полностью готов и проверен, но вот что реально блокирует прод").

---

## 3. Контракты

### 3.1 Agent Service → MCP Tools Server (входной контракт)

Транспорт: MCP **streamable-http** (после правки раздела 0.2), `MultiServerMCPClient({"vera-tools": {"url": MCP_SERVER_URL, "transport": "streamable_http", ...}})`. Этот сервис — реализующая сторона контракта имени/сигнатуры/формата ответа тула; транспорт — совместное решение (раздел 0.1/0.2).

```python
kb_search(query: str, audience: str = "both") -> dict
# audience: "seeker" | "employer" | "both"
```

```json
{
  "chunks": [
    {
      "chunk_id": "uuid",
      "text": "...",
      "synthetic_title": "...",
      "source_title": "ФЗ-181, Статья 21",
      "audience": "both",
      "topics": ["квотирование"],
      "category": "federal_law",
      "section_number": "21",
      "section_title": "...",
      "score": 0.0123
    }
  ]
}
```

Пустой `chunks: []` — валидный ответ ("нет ответа на этот вопрос"), не ошибка. При сбое — **исключение**, не `dict` с полем ошибки (раздел 0.1).

### 3.2 MCP Tools Server → RAG Service (исходящий вызов)

```
POST {RAG_SERVICE_URL}/api/v1/search
Headers: X-API-Key: {RAG_SERVICE_API_KEY}
Body: {"query": str, "audience": "seeker"|"employer"|"both", "top_k": int}
```

Ответ — см. 3.1 (дословно совпадает). Ошибки со стороны RAG: `422` невалидное тело, `500` недоступен Embedding API/reranker после исчерпания собственных ретраев RAG-сервиса, `429` превышен лимит 60 запросов/мин. Таймаут — `RAG_SEARCH_TIMEOUT_SECONDS` (10 секунд по умолчанию: RAG сам может ждать LLM-reranker с собственными ретраями, отводить меньше — риск ложного таймаута до того, как RAG успеет честно ответить).

### 3.3 `GET /health`

```json
{"status": "ok", "rag_service": "ok" | "unreachable"}
```

Код ответа всегда `200` — недоступность RAG Service отражается в теле, не в коде.

---

## 4. Зависимости и риски

| Риск/зависимость | Влияние | Статус |
|---|---|---|
| Инфраструктурные файлы репозитория — копия `vera_agent_service` | До этапа 0 `docker-compose.yml`/`.env.example` вводят в заблуждение (упоминают RabbitMQ/Redis/checkpointer/hypercorn, которых здесь быть не должно) | Закрывается этапом 0 |
| Переход на `streamable-http` требует правок в уже готовом и протестированном `vera_agent_service` | Без раздела 0.2 Этапы 3 и 9 этого плана невозможны; риск сломать часть из 81 существующего теста Agent Service | Явно вынесено в раздел 0.2 с чек-листом |
| ~~Общая Docker-сеть между тремя репозиториями нигде не создана~~ | ~~Блокирует реальный E2E-прогон независимо от готовности кода этого сервиса~~ | Закрыто Этапом 8 — `vera_network`, все три репозитория подключены |
| ~~Три независимых Phoenix-инстанса вместо одного~~ | ~~Трейс запроса не собирается в единое дерево через все сервисы~~ | Закрыто Этапом 8.3 — единственный общий инстанс `vera_agent_phoenix` |
| **`vera_rag_service` не провижинится до рабочего состояния** (`InvalidCatalogNameError: database "vera_rag_service" does not exist`) | Блокирует Этап 9 (сквозной E2E) — реальный запрос через весь путь Agent → MCP → RAG невозможен, пока БД RAG не поднята | Обнаружено при Этапе 8/9 (2026-07-09). Не в рамках этого плана — задача `vera_rag_service`. Сеть/MCP-протокол/контракт `kb_search` подтверждены рабочими независимо от этого блокера |
| Полный корпус документов в RAG Service ещё не загружен (только сырой `Трудовой_кодекс_Российской_Федерации.docx`) | E2E-прогон (этап 9) подтвердит техническую связность, но не полноту/качество ответов по существу | Вне рамок этого плана — зависит от эксперта, отслеживается в `vera_rag_service` |
| Версия `mcp` SDK разойдётся с той, что резолвится у `langchain-mcp-adapters` в Agent Service | Риск протокольной несовместимости streamable-http-транспорта | Зафиксировано явно — `mcp==1.28.1` (раздел 0.1) |
| Agent Service ждёт этот сервис как единственный оставшийся P0-блокер | Любая задержка здесь напрямую блокирует первый реальный запуск всей системы | Информационно — приоритет этого плана высокий |
| Нет per-tool retry-политики — Agent Service ретраит любой тул вслепую | Мутирующий тул (отклик на вакансию, избранное — итерация 3+) может выполниться дважды при ретрае после таймаута, если реально успел выполниться до истечения таймаута | Раздел 0.3 — решить до начала итерации 3+, требует правки контракта, возможно, и на стороне Agent Service |
| Логирование содержимого запросов пользователя без ограничений | Пользовательские запросы к консультанту по правам инвалидов потенциально содержат чувствительные данные о здоровье | Раздел 0.3 — решение зафиксировано (не логировать полный текст на `INFO`), реализовать на этапе 0/5 |
| Contract-тест (этап 6.3) — вручную написанный стаб, не синхронизирован со схемой `vera_rag_service` | Расхождение реального контракта RAG обнаружится не раньше ручного E2E (этап 9) | Известное ограничение, зафиксировано в этапе 6.3 |

---

## 5. Соответствие WBS

Мэппинг на `D:\BKS.Lab\python\my_projects\site_work_for_everyone\AGENT_VERA_WBS.txt`:

| Пункт WBS | Этап этого плана |
|---|---|
| 1.2.3 Анализ вариантов внутренней архитектуры MCP Tools Server | Раздел 0.1 (технические решения) |
| 2.9.1 Контракт Agent Service ↔ MCP Tools Server | Раздел 3.1 |
| 2.9.2 Контракт MCP Tools Server ↔ RAG Service | Раздел 3.2 |
| 3.3.1 Инструмент `kb_search` с Pydantic-валидацией аргументов | Этап 2 |
| 3.3.2 Монтирование FastMCP в FastAPI | Не применимо буквально — сервис не на FastAPI (раздел 0.1); эквивалент — Этап 4 (сборка `main.py`) |
| 3.3.3 HTTP-клиент к RAG Service | Этап 1 |
| 3.3.4 Приём вызовов тулов по MCP-протоколу | Этап 2, 3 |
| 3.3.5 HTTP-запрос к RAG Service и проксирование результата | Этап 1, 2 |
| 3.3.6 Юнит-тесты валидации аргументов | Этап 2.4 |
| 3.3.7 Тесты недоступности RAG Service | Этап 1.3, 3 |
| 3.3.8 Документация инструментов | Этап 10 |
| 3.3.9 Docker-образ, деплой в тестовое окружение | Этап 7 |
| 3.4.1 Сквозная связка трёх сервисов | Этап 8, 9 |
| 3.4.4 E2E-прогон: запрос → ответ со стримингом и источниками | Этап 9 |
| 3.4.6 Итоговые API-контракты для Frontend-разработчика | Раздел 3 (косвенно — контракт RabbitMQ/SSE уже зафиксирован в `AGENT_SERVICE_PLAN.md`, раздел 3.1–3.2, этот план его не меняет) |

---

## 6. Открытые вопросы

~~1. Один общий Phoenix-инстанс на все три сервиса или три независимых~~ — **закрыто (Этап 8.3):** общий — `vera_agent_phoenix`. `vera_mcp_service` подключён; `vera_rag_service` наблюдаемость через Phoenix не имеет вообще (вне рамок этого плана).
2. Точное значение `RAG_SEARCH_TIMEOUT_SECONDS` — предложение по умолчанию 10 секунд (раздел 3.2), нет формального подтверждения.
3. Нужно ли уже сейчас прокидывать `topic`/`category` из `kb_search` в RAG Service (API их уже поддерживает) — сигнатура тула зафиксирована Agent Service как `(query, audience)`; решение отложено на итерацию 2 (раздел 0.1), но стоит подтвердить явно перед тем как её "закрывать" в проде.
~~4. `audience: str` vs `Literal["seeker", "employer", "both"]`~~ — **закрыто:** `Literal` принят (Этап 2.4). Проверено юнит-тестами (`mcp.call_tool`), что невалидный `audience` отклоняется `ToolError` до входа в тело функции — реальную совместимость со схемой, уже забинженной у LLM на стороне Agent Service, окончательно подтвердит только Этап 3 (интеграционный тест против настоящего `MultiServerMCPClient`), не переоткрывать вопрос без причины.
5. `RAG_SERVICE_API_KEY` — сейчас плейсхолдер и в `vera_mcp_service`, и в `vera_rag_service`; нужно реальное значение для локальной совместной разработки (этап 8) и деплоя.
8. **Per-tool retry-политика для мутирующих тулов итерации 3+** (раздел 0.3) — нужен ли idempotency-key в аргументах, или Agent Service должен получить возможность отключать ретрай для конкретных тулов; требует решения и, вероятно, правки на стороне Agent Service до того, как появится первый тул с побочным эффектом.

~~6. Когда вносить правки раздела 0.2 в `vera_agent_service`~~ — **закрыто:** внесены сразу (2026-07-09), все 20 связанных с MCP тестов зелёные, `ruff check .` чист.

~~7. Воспроизводится ли `sse_starlette.sse.AppStatus.should_exit` для streamable-http~~ — **закрыто, воспроизводится:** `mcp` SDK использует `sse_starlette.EventSourceResponse` внутри `streamable_http.py` независимо от названия транспорта. Обход подтверждён и перенесён в `mock_mcp_server.py` (раздел 0.2, "Фактически сделано"). При написании собственного тестового сервера этого сервиса (Этап 3) — тот же обход обязателен.

#!/bin/bash

set -e

# Добавляем в PYTHONPATH корневую директорию проекта (/app), чтобы
# `python -m app.main` резолвился независимо от текущей рабочей директории.
export PYTHONPATH="/app:${PYTHONPATH}"

# Нет реляционной БД/миграций и нет очереди/checkpointer'а в этом сервисе
# (MCP_SERVICE_PLAN.md, раздел 0.1 — сервис полностью stateless) — шагов
# подготовки перед стартом не требуется.

# Сервис сам поднимает встроенный ASGI-сервер через mcp.run(transport=
# "streamable-http") — отдельный hypercorn/uvicorn снаружи не нужен, `mcp`
# SDK уже тянет uvicorn как свою зависимость (MCP_SERVICE_PLAN.md, раздел 0.1).
echo "Starting in production mode..."
exec python -m app.main

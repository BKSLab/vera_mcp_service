from app.health import HealthRegistry


async def test_run_reports_ok_when_check_returns_true():
    registry = HealthRegistry()
    registry.register('rag_service', lambda: _returns(True))

    statuses = await registry.run()

    assert statuses == {'rag_service': 'ok'}


async def test_run_reports_unreachable_when_check_returns_false():
    registry = HealthRegistry()
    registry.register('rag_service', lambda: _returns(False))

    statuses = await registry.run()

    assert statuses == {'rag_service': 'unreachable'}


async def test_run_reports_unreachable_when_check_raises_exception():
    async def failing_check() -> bool:
        raise RuntimeError('boom')

    registry = HealthRegistry()
    registry.register('rag_service', failing_check)

    statuses = await registry.run()

    assert statuses == {'rag_service': 'unreachable'}


async def test_run_reports_multiple_independent_checks():
    registry = HealthRegistry()
    registry.register('rag_service', lambda: _returns(True))
    registry.register('dadata', lambda: _returns(False))

    statuses = await registry.run()

    assert statuses == {'rag_service': 'ok', 'dadata': 'unreachable'}


async def test_run_returns_empty_dict_when_nothing_registered():
    registry = HealthRegistry()

    statuses = await registry.run()

    assert statuses == {}


async def _returns(value: bool) -> bool:
    return value

import pytest

from app import main


def test_run_always_shuts_down_tracing(monkeypatch):
    calls = []

    monkeypatch.setattr(main, 'configure_tracing', lambda settings: calls.append('configure'))
    monkeypatch.setattr(main.mcp, 'run', lambda **kwargs: calls.append(('run', kwargs)))
    monkeypatch.setattr(main, 'shutdown_tracing', lambda: calls.append('shutdown'))

    main.run()

    assert calls == [
        'configure',
        ('run', {'transport': 'streamable-http'}),
        'shutdown',
    ]


def test_run_shuts_down_tracing_when_server_fails(monkeypatch):
    calls = []

    monkeypatch.setattr(main, 'configure_tracing', lambda settings: None)
    monkeypatch.setattr(
        main.mcp,
        'run',
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError('server failed')),
    )
    monkeypatch.setattr(main, 'shutdown_tracing', lambda: calls.append('shutdown'))

    with pytest.raises(RuntimeError, match='server failed'):
        main.run()

    assert calls == ['shutdown']

from __future__ import annotations

from codebase_index.watch.watcher import DebouncedIndexer


class _Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


def test_debouncer_coalesces_burst_into_one_run():
    clock = _Clock()
    runs: list[int] = []
    d = DebouncedIndexer(lambda: runs.append(1), window_s=0.5, clock=clock)

    d.notify(); clock.advance(0.1)
    d.notify(); clock.advance(0.1)
    d.notify()
    assert d.maybe_run() is False        # still inside the quiet window
    assert runs == []

    clock.advance(0.5)                   # window elapsed since last notify
    assert d.maybe_run() is True
    assert runs == [1]                   # the whole burst → exactly one run


def test_debouncer_does_not_run_without_events():
    clock = _Clock()
    runs: list[int] = []
    d = DebouncedIndexer(lambda: runs.append(1), window_s=0.5, clock=clock)
    clock.advance(10)
    assert d.maybe_run() is False
    assert runs == []


def test_debouncer_rearms_after_running():
    clock = _Clock()
    runs: list[int] = []
    d = DebouncedIndexer(lambda: runs.append(1), window_s=0.5, clock=clock)
    d.notify(); clock.advance(0.5); d.maybe_run()
    assert runs == [1]
    d.notify(); clock.advance(0.5); d.maybe_run()
    assert runs == [1, 1]                # second burst runs again


def test_run_watch_without_watchdog_raises_clear_error(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "watchdog" or name.startswith("watchdog."):
            raise ImportError("No module named 'watchdog'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    from codebase_index.watch import watcher
    try:
        watcher.run_watch(config=None, db_path=None, debounce_ms=500)
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "watchdog" in str(exc).lower()
        assert "pip install" in str(exc).lower()

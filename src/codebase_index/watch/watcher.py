"""Optional live indexing (extra: watch).

A burst of filesystem events is coalesced by `DebouncedIndexer` into a single incremental
`update` once edits go quiet for `window_s`, so we never block or thrash the edit loop.
`run_watch` wires that to a watchdog observer; watchdog is imported lazily so the base
install never depends on it.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Callable, Optional


class DebouncedIndexer:
    """Coalesce edit notifications; run the callback once the quiet window elapses.

    Pure and clock-injected for deterministic tests. `notify()` records an edit;
    `maybe_run()` runs the callback exactly once if there is pending work and at least
    `window_s` has passed since the last notification, then re-arms.
    """

    def __init__(
        self,
        callback: Callable[[], None],
        *,
        window_s: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._callback = callback
        self._window_s = window_s
        self._clock = clock
        self._last_event: Optional[float] = None

    def notify(self) -> None:
        self._last_event = self._clock()

    def maybe_run(self) -> bool:
        if self._last_event is None:
            return False
        if self._clock() - self._last_event < self._window_s - 1e-9:
            return False
        self._last_event = None
        self._callback()
        return True


def run_watch(config, db_path, debounce_ms: int) -> None:  # pragma: no cover - exercised via CLI/manual QA
    """Watch the repo and run incremental `update` on debounced changes.

    Raises RuntimeError (not ImportError) with install guidance if watchdog is absent.
    """
    try:
        from watchdog.events import FileSystemEventHandler
        from watchdog.observers import Observer
    except ImportError as exc:
        raise RuntimeError(
            "watch mode requires the optional 'watchdog' dependency. "
            'Install it with: pip install "codebase-index[watch]"'
        ) from exc

    from ..indexer.pipeline import update_index
    from ..storage.db import Database

    root = Path(config.root).resolve()

    def _run_update() -> None:
        with Database(db_path) as db:
            stats = update_index(config, db, root=root)
        if stats.indexed or stats.deleted:
            print(f"[watch] updated {stats.indexed}, pruned {stats.deleted}", flush=True)

    debouncer = DebouncedIndexer(_run_update, window_s=debounce_ms / 1000.0)

    class _Handler(FileSystemEventHandler):
        def on_any_event(self, event) -> None:
            if not event.is_directory:
                debouncer.notify()

    observer = Observer()
    observer.schedule(_Handler(), str(root), recursive=True)
    observer.start()
    print(f"[watch] watching {root} (debounce {debounce_ms}ms). Ctrl-C to stop.", flush=True)
    try:
        while True:
            time.sleep(min(0.25, debounce_ms / 1000.0))
            debouncer.maybe_run()
    except KeyboardInterrupt:
        pass
    finally:
        observer.stop()
        observer.join()

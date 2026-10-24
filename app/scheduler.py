import logging
import time
from datetime import timedelta
from threading import Condition, Lock, Thread
from typing import Any

from app.domain import Conflict, InvalidInput, utcnow
from app.services import CryptoService

logger = logging.getLogger(__name__)


class Scheduler:
    def __init__(self, service: CryptoService) -> None:
        self.service = service
        self._condition = Condition()
        self._run_lock = Lock()
        self._thread: Thread | None = None
        self._stopped = False
        self._enabled = True
        self._interval = 30
        self._last = None
        self._next = utcnow() + timedelta(seconds=30)
        self._deadline = time.monotonic() + 30
        self._revision = 0

    def start(self) -> None:
        with self._condition:
            if self._thread is not None:
                raise RuntimeError("Scheduler already started")
            self._thread = Thread(target=self._loop, name="crypto-updater", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        with self._condition:
            self._stopped = True
            self._condition.notify_all()
        if self._thread is not None:
            self._thread.join()

    def _plan(self) -> None:
        self._next = utcnow() + timedelta(seconds=self._interval) if self._enabled else None
        self._deadline = time.monotonic() + self._interval

    def configure(self, enabled: bool, interval_seconds: int) -> dict[str, Any]:
        if (
            type(enabled) is not bool
            or type(interval_seconds) is not int
            or not 10 <= interval_seconds <= 3600
        ):
            raise InvalidInput("Interval must be an integer between 10 and 3600 seconds")
        with self._condition:
            self._enabled = enabled
            self._interval = interval_seconds
            self._revision += 1
            self._plan()
            self._condition.notify_all()
            return {"enabled": enabled, "interval_seconds": interval_seconds}

    def settings(self) -> dict[str, Any]:
        with self._condition:
            return {
                "enabled": self._enabled,
                "interval_seconds": self._interval,
                "last_update": self._last,
                "next_update": self._next,
            }

    def _execute(self) -> dict[str, Any]:
        count = self.service.refresh_all()
        stamp = utcnow()
        with self._condition:
            self._last = stamp
        return {"updated_count": count, "timestamp": stamp}

    def trigger(self) -> dict[str, Any]:
        if not self._run_lock.acquire(blocking=False):
            raise Conflict("A bulk update is already running; retry later")
        try:
            return self._execute()
        finally:
            self._run_lock.release()

    def _loop(self) -> None:
        while True:
            with self._condition:
                while not self._stopped:
                    delay = self._deadline - time.monotonic()
                    if self._enabled and delay <= 0:
                        break
                    self._condition.wait(delay if self._enabled else None)
                if self._stopped:
                    return
                revision = self._revision
            started = False
            try:
                with self._run_lock:
                    with self._condition:
                        if self._stopped or not self._enabled or revision != self._revision:
                            continue
                    started = True
                    self._execute()
            except Exception:
                logger.exception("Scheduled price update failed")
            finally:
                with self._condition:
                    if started:
                        self._plan()

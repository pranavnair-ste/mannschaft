"""A tiny process supervisor for the one-command observability launcher.

One responsibility: own N child processes — spawn them, poll readiness via an
optional health URL, watch for an early exit, and tear them all down on signal
or atexit. No business logic; the CLI builds the ``Proc`` list.
"""

from __future__ import annotations

import atexit
import signal
import subprocess
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Proc:
    name: str
    argv: list[str]
    cwd: Path | None = None
    env: dict | None = None
    health_url: str | None = None  # GET that returns <500 when ready


class Supervisor:
    def __init__(self, procs: list[Proc], *, sleep=time.sleep):
        self.procs = procs
        self._sleep = sleep
        self._children: list[tuple[Proc, subprocess.Popen]] = []
        self._tearing_down = False

    def start(self) -> None:
        for p in self.procs:
            child = subprocess.Popen(
                p.argv,
                cwd=str(p.cwd) if p.cwd else None,
                env=p.env,
                stdin=subprocess.DEVNULL,
            )
            self._children.append((p, child))

    def wait_ready(
        self, *, timeout: float = 30.0, interval: float = 0.5
    ) -> dict[str, bool]:
        """Poll each health-checked proc until ready or the timeout elapses.

        Returns a per-proc readiness report ``{name -> bool}`` covering only the
        procs that declare a ``health_url`` (procs without one are not probed and
        are absent from the report). The caller surfaces not-ready procs.
        """
        deadline = time.monotonic() + timeout
        report: dict[str, bool] = {}
        for p, _ in self._children:
            if not p.health_url:
                continue
            ready = False
            while True:
                if self._probe(p.health_url):
                    ready = True
                    break
                if time.monotonic() >= deadline:
                    break
                self._sleep(interval)
            report[p.name] = ready
        return report

    @staticmethod
    def _probe(url: str) -> bool:
        try:
            with urllib.request.urlopen(url, timeout=2.0) as r:
                return r.status < 500
        except Exception:
            return False

    def poll_once(self) -> Proc | None:
        for p, child in self._children:
            if child.poll() is not None:
                return p  # a child exited
        return None

    def teardown(self) -> None:
        if self._tearing_down:
            return
        self._tearing_down = True
        for _, child in reversed(self._children):
            try:
                child.terminate()
            except Exception:
                pass
        for _, child in reversed(self._children):
            try:
                child.wait(timeout=5)
            except Exception:
                try:
                    child.kill()
                except Exception:
                    pass

    def run(
        self,
        *,
        ready_timeout: float = 30.0,
        poll_interval: float = 1.0,
        strict: bool = False,
        on_ready=None,
    ) -> int:
        """Spawn, wait for readiness, then watch until a child exits or signal.

        ``on_ready`` (if given) is called once with the per-proc readiness report
        so the caller can surface which procs came up. When ``strict`` is True and
        any health-checked proc is not ready, return non-zero immediately (after
        tearing down) instead of tailing.
        """
        atexit.register(self.teardown)

        def _handler(signum, frame):
            self.teardown()
            raise SystemExit(128 + signum)

        signal.signal(signal.SIGINT, _handler)
        signal.signal(signal.SIGTERM, _handler)
        self.start()
        try:
            report = self.wait_ready(timeout=ready_timeout)
            if on_ready is not None:
                on_ready(report)
            if strict and not all(report.values()):
                return 2
            while True:
                dead = self.poll_once()
                if dead is not None:
                    return 1
                self._sleep(poll_interval)
        finally:
            self.teardown()

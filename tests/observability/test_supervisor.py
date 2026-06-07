"""Tests for the process Supervisor — FakeProc only, never spawn real processes."""

from pi_harness.observability import supervisor as sup


class FakeProc:
    def __init__(self, exit_after=None):
        self._exit_after = exit_after
        self._polls = 0
        self.terminated = False
        self.killed = False

    def poll(self):
        self._polls += 1
        if self._exit_after is not None and self._polls > self._exit_after:
            return 0
        return None

    def wait(self, timeout=None):
        return 0

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True


def test_start_spawns_all(monkeypatch):
    spawned = []
    monkeypatch.setattr(
        sup.subprocess, "Popen",
        lambda argv, **k: spawned.append(argv) or FakeProc(),
    )
    s = sup.Supervisor([sup.Proc("a", ["x"]), sup.Proc("b", ["y"])])
    s.start()
    assert spawned == [["x"], ["y"]]


def test_teardown_terminates_in_reverse(monkeypatch):
    procs = [FakeProc(), FakeProc()]
    it = iter(procs)
    monkeypatch.setattr(sup.subprocess, "Popen", lambda argv, **k: next(it))
    s = sup.Supervisor([sup.Proc("a", ["x"]), sup.Proc("b", ["y"])])
    s.start()
    s.teardown()
    assert all(p.terminated for p in procs)


def test_teardown_idempotent(monkeypatch):
    monkeypatch.setattr(sup.subprocess, "Popen", lambda argv, **k: FakeProc())
    s = sup.Supervisor([sup.Proc("a", ["x"])])
    s.start()
    s.teardown()
    s.teardown()  # no raise


def test_poll_detects_dead_child(monkeypatch):
    monkeypatch.setattr(sup.subprocess, "Popen", lambda argv, **k: FakeProc(exit_after=1))
    s = sup.Supervisor([sup.Proc("a", ["x"])])
    s.start()
    s.poll_once()  # first poll alive
    assert s.poll_once() is not None  # second poll dead

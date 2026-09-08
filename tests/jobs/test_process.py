"""Real process groups establish ownership and cleanup behavior."""

import json
import signal
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import BinaryIO

import psutil
import pytest

from resinsight_mcp.contracts.sessions import ProcessIdentity
from resinsight_mcp.jobs._process import (
    OwnedProcess,
    ProcessInspectionBusy,
    ProcessLaunchError,
    ProcessOwnershipError,
)


def wait_for(condition: Callable[[], bool]) -> None:
    deadline = time.monotonic() + 10
    while True:
        try:
            if condition():
                return
        except ProcessInspectionBusy:
            pass
        if time.monotonic() >= deadline:
            pytest.fail("The child process did not reach its expected state.")
        time.sleep(0.02)


def run_when_stable[T](operation: Callable[[], T]) -> T:
    result: list[T] = []

    def attempt() -> bool:
        result.append(operation())
        return True

    wait_for(attempt)
    return result[0]


@pytest.fixture
def launch(tmp_path: Path) -> Iterator[Callable[[str], OwnedProcess]]:
    owners: list[OwnedProcess] = []
    with (tmp_path / "stdout.log").open("wb") as stdout:
        with (tmp_path / "stderr.log").open("wb") as stderr:

            def start(source: str) -> OwnedProcess:
                owner = OwnedProcess.start((sys.executable, "-c", source), tmp_path, stdout, stderr)
                owners.append(owner)
                return owner

            yield start
            for owner in owners:
                if owner._finished:
                    continue
                wait_for(lambda owner=owner: owner.signal_group(signal.SIGKILL) is None)
                wait_for(lambda owner=owner: not owner.live_members())
                run_when_stable(owner.finish)


def test_cancel_real_child_tree(launch: Callable[[str], OwnedProcess], tmp_path: Path) -> None:
    owner = launch(
        "import json, pathlib, subprocess, sys, time; "
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
        "pathlib.Path('ready.json').write_text(json.dumps(child.pid)); time.sleep(60)"
    )
    ready = tmp_path / "ready.json"
    wait_for(ready.exists)
    child_pid = json.loads(ready.read_text())
    assert set(run_when_stable(owner.live_members)) == {owner.identity.pid, child_pid}
    with pytest.raises(ProcessOwnershipError, match="live members"):
        run_when_stable(owner.close)
    owner.signal_group(signal.SIGTERM)
    wait_for(lambda: not owner.live_members())
    assert run_when_stable(owner.finish) == -signal.SIGTERM
    with pytest.raises(ProcessOwnershipError, match="reaped"):
        owner.signal_group(signal.SIGKILL)


def test_exited_leader_retains_child_group(
    launch: Callable[[str], OwnedProcess], tmp_path: Path
) -> None:
    owner = launch(
        "import json, pathlib, subprocess, sys; "
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
        "pathlib.Path('ready.json').write_text(json.dumps(child.pid))"
    )
    wait_for(owner.leader_exited)
    child_pid = json.loads((tmp_path / "ready.json").read_text())
    assert run_when_stable(owner.live_members) == (child_pid,)
    assert psutil.Process(owner.identity.pid).status() == psutil.STATUS_ZOMBIE
    with pytest.raises(ProcessOwnershipError, match="live members"):
        run_when_stable(owner.finish)
    owner.signal_group(signal.SIGKILL)
    wait_for(lambda: not owner.live_members())
    assert run_when_stable(owner.finish) == 0


def test_escalate_ignored_termination(
    launch: Callable[[str], OwnedProcess], tmp_path: Path
) -> None:
    owner = launch(
        "import pathlib, signal, time; "
        "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        "pathlib.Path('ready').touch(); time.sleep(60)"
    )
    wait_for((tmp_path / "ready").exists)
    owner.signal_group(signal.SIGTERM)
    assert run_when_stable(owner.live_members) == (owner.identity.pid,)
    owner.signal_group(signal.SIGKILL)
    wait_for(lambda: not owner.live_members())
    assert run_when_stable(owner.finish) == -signal.SIGKILL


def test_stale_identity_never_signals_unrelated_process(
    launch: Callable[[str], OwnedProcess], monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = launch("import time; time.sleep(60)")
    with subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"]) as unrelated:
        try:
            identity = ProcessIdentity(
                pid=unrelated.pid,
                start_marker=str(psutil.Process(unrelated.pid).create_time()),
            )
            with monkeypatch.context() as patch:
                patch.setattr(owner, "_identity", identity)
                with pytest.raises(ProcessOwnershipError, match="no longer matches"):
                    owner.signal_group(signal.SIGKILL)
            assert unrelated.poll() is None
            assert run_when_stable(owner.live_members) == (owner.identity.pid,)
        finally:
            unrelated.terminate()
            unrelated.wait()


@pytest.mark.parametrize("handler", [signal.SIG_IGN, lambda signum, frame: None])
def test_reject_unsafe_sigchld_policy(
    launch: Callable[[str], OwnedProcess], handler: signal.Handlers | Callable[..., None]
) -> None:
    previous = signal.signal(signal.SIGCHLD, handler)
    try:
        with pytest.raises(ProcessOwnershipError, match="default SIGCHLD"):
            launch("raise RuntimeError('This command must not start')")
    finally:
        signal.signal(signal.SIGCHLD, previous)


def test_membership_access_failure_is_visible(
    launch: Callable[[str], OwnedProcess], monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = launch("import time; time.sleep(60)")

    def unavailable() -> list[int]:
        raise psutil.AccessDenied(owner.identity.pid)

    monkeypatch.setattr(psutil, "pids", unavailable)
    with pytest.raises(ProcessOwnershipError, match="membership is unavailable"):
        owner.live_members()
    monkeypatch.undo()


def test_changed_start_marker_blocks_group_signal(
    launch: Callable[[str], OwnedProcess], monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = launch("import time; time.sleep(60)")
    stale = ProcessIdentity(pid=owner.identity.pid, start_marker="another lifetime")
    with monkeypatch.context() as patch:
        patch.setattr(owner, "_identity", stale)
        with pytest.raises(ProcessOwnershipError, match="no longer matches"):
            owner.signal_group(signal.SIGTERM)
    assert run_when_stable(owner.live_members) == (owner.identity.pid,)


def test_startup_inspection_failure_does_not_signal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    children: list[subprocess.Popen[bytes]] = []
    popen = subprocess.Popen

    def capture(
        argv: tuple[str, ...],
        *,
        cwd: Path,
        stdin: int,
        stdout: BinaryIO,
        stderr: BinaryIO,
        start_new_session: bool,
    ) -> subprocess.Popen[bytes]:
        child = popen(
            argv,
            cwd=cwd,
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
            start_new_session=start_new_session,
        )
        children.append(child)
        return child

    def unavailable(self: OwnedProcess) -> psutil.Process:
        raise ProcessOwnershipError("Ownership is unproved.")

    signals: list[tuple[int, int]] = []
    monkeypatch.setattr(subprocess, "Popen", capture)
    monkeypatch.setattr(OwnedProcess, "_verify", unavailable)
    monkeypatch.setattr("os.killpg", lambda pid, sig: signals.append((pid, sig)))
    try:
        with (tmp_path / "log").open("wb") as log:
            with pytest.raises(ProcessOwnershipError, match="unproved"):
                OwnedProcess.start(
                    (sys.executable, "-c", "import time; time.sleep(60)"), tmp_path, log, log
                )
        assert not signals
        assert children[0].poll() is None
    finally:
        for child in children:
            child.kill()
            child.wait()


def test_missing_executable_reports_launch_failure(tmp_path: Path) -> None:
    with (tmp_path / "log").open("wb") as log:
        with pytest.raises(ProcessLaunchError) as failure:
            OwnedProcess.start((str(tmp_path / "missing-command"),), tmp_path, log, log)
    assert isinstance(failure.value.__cause__, FileNotFoundError)


def test_child_created_after_pid_snapshot_prevents_empty_result(
    launch: Callable[[str], OwnedProcess], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = launch(
        "import pathlib, subprocess, sys, time\n"
        "pathlib.Path('ready').touch()\n"
        "while not pathlib.Path('go').exists(): time.sleep(0.005)\n"
        "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
    )
    wait_for((tmp_path / "ready").exists)
    pids = psutil.pids
    first = True

    def raced_snapshot() -> list[int]:
        nonlocal first
        snapshot = pids()
        if first:
            first = False
            (tmp_path / "go").touch()
            wait_for(owner.leader_exited)
        return snapshot

    with monkeypatch.context() as patch:
        patch.setattr(psutil, "pids", raced_snapshot)
        try:
            members = owner.live_members()
        except ProcessInspectionBusy:
            pass
        else:
            assert members
    with pytest.raises(ProcessOwnershipError, match="live members"):
        run_when_stable(owner.finish)


def test_changed_inventory_rejects_empty_confirmation(
    launch: Callable[[str], OwnedProcess], monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = launch("pass")
    wait_for(owner.leader_exited)
    snapshots = iter(([owner.identity.pid], [owner.identity.pid, psutil.Process().pid]))
    with monkeypatch.context() as patch:
        patch.setattr(psutil, "pids", lambda: next(snapshots))
        with pytest.raises(ProcessInspectionBusy, match="identities changed"):
            owner.finish()
    assert psutil.Process(owner.identity.pid).status() == psutil.STATUS_ZOMBIE


def test_empty_command_argument_is_preserved(launch: Callable[[str], OwnedProcess]) -> None:
    owner = launch("")
    wait_for(owner.leader_exited)
    assert run_when_stable(owner.finish) == 0

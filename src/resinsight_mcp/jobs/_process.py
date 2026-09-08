"""Own one child group while retaining its unreaped leader.

The caller must not reap children or change SIGCHLD handling outside this owner.
Commands and descendants must remain in their original process group.
Keep this object alive until finish succeeds. Destruction does not cancel a job.
"""

import os
import signal
import subprocess
import threading
from pathlib import Path
from typing import BinaryIO

import psutil

from resinsight_mcp.contracts.sessions import ProcessIdentity


class ProcessOwnershipError(RuntimeError):
    """The process owner cannot establish a safe operation."""


class ProcessLaunchError(ProcessOwnershipError):
    """The command failed before execution started."""


class ProcessInspectionBusy(ProcessOwnershipError):
    """Process churn prevents a stable empty group observation."""


def _require_signal_policy() -> None:
    if signal.getsignal(signal.SIGCHLD) != signal.SIG_DFL:
        raise ProcessOwnershipError("Job ownership requires default SIGCHLD handling.")


class OwnedProcess:
    """Retain a child without reaping it before the final group signal.

    This class cannot attach to saved process identifiers.
    The dedicated supervisor must be the only code that waits for its child.
    """

    _child: subprocess.Popen[bytes]
    _identity: ProcessIdentity
    _lock: threading.RLock
    _finished: bool

    def __init__(self) -> None:
        raise TypeError("Use OwnedProcess.start() to create an owned child.")

    @classmethod
    def start(
        cls, argv: tuple[str, ...], cwd: Path, stdout: BinaryIO, stderr: BinaryIO
    ) -> "OwnedProcess":
        """Start a trusted command in a new session without a shell."""
        _require_signal_policy()
        if (
            not argv
            or not argv[0]
            or any(not isinstance(item, str) or "\0" in item for item in argv)
        ):
            raise ValueError("A command requires an executable and valid string arguments.")
        owner = object.__new__(cls)
        owner._lock = threading.RLock()
        owner._finished = False
        try:
            owner._child = subprocess.Popen(
                argv,
                cwd=cwd,
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                start_new_session=True,
            )
        except OSError as error:
            raise ProcessLaunchError("The job command could not start.") from error
        process = psutil.Process(owner._child.pid)
        owner._identity = ProcessIdentity(pid=process.pid, start_marker=str(process.create_time()))
        # Failed inspection does not authorize cleanup signals or a wait for this child.
        owner._verify()
        return owner

    @property
    def identity(self) -> ProcessIdentity:
        return self._identity

    @property
    def group_id(self) -> int:
        return self._child.pid

    def _verify(self) -> psutil.Process:
        _require_signal_policy()
        if self._finished or self._child.returncode is not None:
            raise ProcessOwnershipError("The child has already been reaped.")
        try:
            process = psutil.Process(self._child.pid)
            actual = ProcessIdentity(pid=process.pid, start_marker=str(process.create_time()))
            if actual != self.identity or process.ppid() != os.getpid():
                raise ProcessOwnershipError("The owned child identity no longer matches.")
            return process
        except (psutil.Error, OSError) as error:
            raise ProcessOwnershipError("The owned child identity is unavailable.") from error

    def leader_exited(self) -> bool:
        """Inspect leader termination without consuming its exit status."""
        with self._lock:
            try:
                return self._verify().status() == psutil.STATUS_ZOMBIE
            except psutil.Error as error:
                raise ProcessOwnershipError("The child status is unavailable.") from error

    def _scan(self) -> tuple[dict[int, float], tuple[int, ...]]:
        inventory: dict[int, float] = {}
        members: list[int] = []
        try:
            for pid in psutil.pids():
                process = psutil.Process(pid)
                inventory[pid] = process.create_time()
                if process.status() == psutil.STATUS_ZOMBIE:
                    continue
                if os.getpgid(pid) == self.group_id:
                    members.append(pid)
        except (ProcessLookupError, psutil.NoSuchProcess) as error:
            raise ProcessInspectionBusy("A process disappeared during group inspection.") from error
        except (OSError, psutil.Error) as error:
            raise ProcessOwnershipError("Process group membership is unavailable.") from error
        return inventory, tuple(sorted(members))

    def live_members(self) -> tuple[int, ...]:
        """Return observed live members or establish a stable empty observation.

        Empty results require two matching process identity inventories.
        Process churn prevents confirmation because enumeration is not atomic.
        Nonempty results identify observed members without claiming a complete census.
        """
        with self._lock:
            self._verify()
            first, members = self._scan()
            if not members:
                second, members = self._scan()
                if not members and first != second:
                    raise ProcessInspectionBusy("Process identities changed during inspection.")
            self._verify()
            return members

    def signal_group(self, sig: int) -> None:
        """Signal only the group pinned by this owner's unreaped direct child."""
        with self._lock:
            self._verify()
            try:
                os.killpg(self.group_id, sig)
            except (ProcessLookupError, PermissionError):
                if self.live_members():
                    raise ProcessOwnershipError(
                        "The process group could not be signaled."
                    ) from None

    def finish(self) -> int:
        """Reap the leader only after observing no live group members."""
        with self._lock:
            if self.live_members():
                raise ProcessOwnershipError("The process group still contains live members.")
            if not self.leader_exited():
                raise ProcessOwnershipError("The group leader has not exited.")
            result = self._child.wait()
            self._finished = True
            return result

    def close(self) -> int:
        """Finish a stopped group. Reject live groups without canceling them."""
        return self.finish()

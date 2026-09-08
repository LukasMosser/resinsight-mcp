"""ResInsight RPC access with host process verification and bounded calls.

Endpoint ownership uses lsof on the supported host. It does not use port scans.
Project observations do not provide a complete change history.
"""

import logging
import math
import shutil
import subprocess
import time
import uuid
from collections import namedtuple
from collections.abc import Callable
from importlib.metadata import version
from pathlib import Path
from typing import Protocol, cast

import grpc
import psutil
import rips
from rips.generated import App_pb2_grpc, Definitions_pb2

from resinsight_mcp.contracts.errors import ContractError, Error, ErrorCode, MutationEffect
from resinsight_mcp.contracts.sessions import Endpoint, ObjectKind, ProcessIdentity

from ._backend import NativeObject, ProjectSnapshot

_LOG = logging.getLogger(__name__)


def _failure(code: ErrorCode, message: str, *, uncertain: bool = False) -> ContractError:
    _LOG.error(message)
    return ContractError(
        Error(
            code=code,
            message=message,
            effect=MutationEffect.UNKNOWN if uncertain else MutationEffect.NOT_APPLIED,
        )
    )


def _identity(pid: int) -> ProcessIdentity:
    try:
        process = psutil.Process(pid)
        if not process.is_running() or process.status() == psutil.STATUS_ZOMBIE:
            raise psutil.NoSuchProcess(pid)
        return ProcessIdentity(pid=pid, start_marker=str(process.create_time()))
    except psutil.Error as error:
        raise _failure(
            ErrorCode.LOST_CONNECTION, f"Cannot verify process {pid}: {error}"
        ) from error


def _listener(endpoint: Endpoint, timeout: float) -> ProcessIdentity:
    executable = shutil.which("lsof")
    if executable is None:
        raise _failure(ErrorCode.EXECUTION_FAILED, "Endpoint verification requires lsof.")
    try:
        result = subprocess.run(
            [executable, "-nP", f"-iTCP@{endpoint.host}:{endpoint.port}", "-sTCP:LISTEN", "-Fp"],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise _failure(
            ErrorCode.LOST_CONNECTION, f"Endpoint verification failed: {error}"
        ) from error
    try:
        pids = {int(line[1:]) for line in result.stdout.splitlines() if line.startswith("p")}
    except ValueError as error:
        raise _failure(
            ErrorCode.LOST_CONNECTION,
            "Endpoint verification returned an invalid process identifier.",
        ) from error
    if result.returncode != 0 or len(pids) != 1:
        raise _failure(
            ErrorCode.LOST_CONNECTION,
            f"Endpoint {endpoint.host}:{endpoint.port} has no uniquely verified listener.",
        )
    return _identity(pids.pop())


class _CallDetails(
    namedtuple("_Details", "method timeout metadata credentials wait_for_ready compression"),
    grpc.ClientCallDetails,
):
    pass


class _Deadline(grpc.UnaryUnaryClientInterceptor):
    def __init__(self, timeout: float) -> None:
        self.timeout = timeout

    def intercept_unary_unary(self, continuation, client_call_details, request):
        timeout = client_call_details.timeout
        details = _CallDetails(
            client_call_details.method,
            self.timeout if timeout is None else min(timeout, self.timeout),
            client_call_details.metadata,
            client_call_details.credentials,
            client_call_details.wait_for_ready,
            client_call_details.compression,
        )
        return continuation(details, request)


class _Object(Protocol):
    def address(self) -> int: ...


class _Case(_Object, Protocol):
    id: int
    name: str
    file_path: str | None


class _View(_Object, Protocol):
    id: int


class _Well(_Object, Protocol):
    name: str


class _Project(_Object, Protocol):
    def cases(self) -> list[_Case]: ...
    def views(self) -> list[_View]: ...
    def well_paths(self) -> list[_Well]: ...
    def open(self, path: str) -> object: ...
    def save(self, path: str) -> object: ...
    def close(self) -> None: ...


class _ProjectType(Protocol):
    def create(self, channel: grpc.Channel) -> _Project: ...


def _rpc[T](action: Callable[[], T], *, mutation: bool = False) -> T:
    try:
        return action()
    except (grpc.RpcError, rips.RipsError) as error:
        code = cast(grpc.Call, error).code() if isinstance(error, grpc.RpcError) else error.code
        if code == grpc.StatusCode.DEADLINE_EXCEEDED:
            mapped = ErrorCode.BUSY
        elif code in (grpc.StatusCode.UNAVAILABLE, grpc.StatusCode.CANCELLED):
            mapped = ErrorCode.LOST_CONNECTION
        else:
            mapped = ErrorCode.EXECUTION_FAILED
        raise _failure(mapped, f"ResInsight call failed: {error}", uncertain=mutation) from error


class RipsApplication:
    """One verified application process and one client channel."""

    def __init__(self, endpoint: Endpoint, process: ProcessIdentity, timeout: float) -> None:
        self._endpoint = endpoint
        self._process = process
        self._timeout = timeout
        self._disconnected = False
        self._channel = grpc.insecure_channel(
            f"{endpoint.host}:{endpoint.port}", options=[("grpc.enable_http_proxy", False)]
        )
        self._calls = grpc.intercept_channel(self._channel, _Deadline(timeout))
        self._app = App_pb2_grpc.AppStub(self._calls)
        try:
            self.verify_process()
            observed = _rpc(lambda: self._app.GetVersion(Definitions_pb2.Empty()))
            expected = tuple(int(part) for part in version("rips").split(".")[:2])
            if (observed.major_version, observed.minor_version) != expected:
                raise _failure(
                    ErrorCode.EXECUTION_FAILED,
                    f"ResInsight version does not match rips {version('rips')}.",
                )
            self.verify_process()
        except Exception:
            self.disconnect()
            raise

    @property
    def endpoint(self) -> Endpoint:
        return self._endpoint

    @property
    def process(self) -> ProcessIdentity:
        return self._process

    def verify_process(self) -> ProcessIdentity:
        if self._disconnected:
            raise _failure(ErrorCode.LOST_CONNECTION, "The client channel is disconnected.")
        if _identity(self.process.pid) != self.process:
            raise _failure(ErrorCode.LOST_CONNECTION, "The recorded process lifetime has ended.")
        if _listener(self.endpoint, self._timeout) != self.process:
            raise _failure(ErrorCode.LOST_CONNECTION, "The endpoint belongs to another process.")
        return self.process

    def _project(self) -> _Project:
        return cast(_ProjectType, rips.Project).create(self._calls)

    def snapshot(self) -> ProjectSnapshot:
        self.verify_process()
        return _rpc(self._snapshot)

    def _snapshot(self) -> ProjectSnapshot:
        project = self._project()
        objects: list[NativeObject] = []
        for case in project.cases():
            attributes = (("id", str(case.id)), ("file_path", case.file_path or ""))
            objects.append(
                NativeObject(ObjectKind.CASE, str(case.address()), case.name, attributes)
            )
        for view in project.views():
            objects.append(
                NativeObject(
                    ObjectKind.VIEW, str(view.address()), f"View {view.id}", (("id", str(view.id)),)
                )
            )
        for well in project.well_paths():
            objects.append(NativeObject(ObjectKind.WELL, str(well.address()), well.name))
        return ProjectSnapshot(
            str(project.address()),
            tuple(sorted(objects, key=lambda item: (item.kind, item.address))),
        )

    def open_project(self, path: Path) -> None:
        self.verify_process()
        project = _rpc(self._project)
        _rpc(lambda: project.open(str(path)), mutation=True)

    def save_project(self, path: Path) -> None:
        self.verify_process()
        project = _rpc(self._project)
        _rpc(lambda: project.save(str(path)), mutation=True)

    def close_project(self) -> None:
        self.verify_process()
        project = _rpc(self._project)
        _rpc(project.close, mutation=True)

    def disconnect(self) -> None:
        self._disconnected = True
        self._channel.close()

    def terminate(self) -> None:
        self.verify_process()
        try:
            process = psutil.Process(self.process.pid)
            marker = str(process.create_time())
        except psutil.Error as error:
            raise _failure(
                ErrorCode.LOST_CONNECTION, f"Cannot verify process before exit: {error}"
            ) from error
        if marker != self.process.start_marker:
            raise _failure(ErrorCode.LOST_CONNECTION, "The recorded process lifetime has ended.")
        _rpc(lambda: self._app.Exit(Definitions_pb2.Empty()), mutation=True)
        try:
            process.wait(timeout=self._timeout)
        except psutil.NoSuchProcess:
            pass
        except psutil.Error as error:
            raise _failure(
                ErrorCode.EXECUTION_FAILED,
                f"ResInsight exit was not confirmed: {error}",
                uncertain=True,
            ) from error


class RipsApplicationFactory:
    """Launch or attach without selecting an alternate endpoint."""

    def __init__(
        self, log_directory: Path, launch_timeout: float = 120, rpc_timeout: float = 30
    ) -> None:
        if not all(math.isfinite(value) and value > 0 for value in (launch_timeout, rpc_timeout)):
            raise ValueError("Timeouts must be finite and positive.")
        self._logs = log_directory
        self._launch_timeout = launch_timeout
        self._rpc_timeout = rpc_timeout

    def attach(self, endpoint: Endpoint) -> RipsApplication:
        return RipsApplication(endpoint, _listener(endpoint, self._rpc_timeout), self._rpc_timeout)

    def launch(self, executable: Path) -> RipsApplication:
        if not executable.is_absolute():
            raise _failure(
                ErrorCode.INVALID_PATH, "The application executable path must be absolute."
            )
        launch_id = uuid.uuid4().hex
        port_file = self._logs / f"{launch_id}.port"
        log_file = self._logs / f"{launch_id}.log"
        try:
            self._logs.mkdir(parents=True, exist_ok=True)
            with log_file.open("x") as log:
                process = subprocess.Popen(
                    [str(executable), "--server", "0", "--portnumberfile", str(port_file)],
                    stdout=log,
                    stderr=subprocess.STDOUT,
                )
        except OSError as error:
            raise _failure(
                ErrorCode.EXECUTION_FAILED, f"ResInsight launch failed: {error}"
            ) from error
        _LOG.info("Launched ResInsight PID %s. Output: %s", process.pid, log_file)
        try:
            identity = _identity(process.pid)
            endpoint = self._wait_for_endpoint(process, port_file)
            return RipsApplication(endpoint, identity, self._rpc_timeout)
        except ContractError as error:
            raise _failure(
                error.error.code,
                f"{error} Launched PID: {process.pid}. Output: {log_file}",
                uncertain=process.poll() is None,
            ) from error

    def _wait_for_endpoint(self, process: subprocess.Popen, port_file: Path) -> Endpoint:
        deadline = time.monotonic() + self._launch_timeout
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise _failure(ErrorCode.EXECUTION_FAILED, "ResInsight exited during launch.")
            if port_file.exists():
                try:
                    value = port_file.read_text().strip()
                    if value:
                        return Endpoint(port=int(value))
                except (OSError, ValueError) as error:
                    raise _failure(
                        ErrorCode.EXECUTION_FAILED, "ResInsight wrote an invalid port file."
                    ) from error
            time.sleep(min(0.05, max(0, deadline - time.monotonic())))
        raise _failure(ErrorCode.BUSY, "ResInsight launch timed out.")

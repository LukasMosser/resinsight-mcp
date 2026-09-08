"""Deterministic applications expose calls and controlled failures."""

from pathlib import Path
from threading import Event

from resinsight_mcp.contracts.errors import Error, Failure, OperationResult, Success
from resinsight_mcp.contracts.sessions import Endpoint, ObjectKind, ProcessIdentity
from resinsight_mcp.resinsight.sessions._backend import NativeObject, ProjectSnapshot


def value[T](result: OperationResult[T]) -> T:
    assert isinstance(result.outcome, Success), result.model_dump(mode="json")
    return result.outcome.value


def error[T](result: OperationResult[T]) -> Error:
    assert isinstance(result.outcome, Failure), result.model_dump(mode="json")
    return result.outcome.error


class ApplicationDouble:
    def __init__(self, port: int) -> None:
        self.endpoint = Endpoint(port=port)
        self.process = ProcessIdentity(pid=port, start_marker=f"started-{port}")
        self.verified_process = self.process
        self.project = ProjectSnapshot("root", (NativeObject(ObjectKind.CASE, "case-0", "Case"),))
        self.calls: list[tuple[str, Path | None]] = []
        self.failure: Exception | None = None
        self.entered: Event | None = None
        self.release: Event | None = None

    def verify_process(self) -> ProcessIdentity:
        return self.verified_process

    def snapshot(self) -> ProjectSnapshot:
        if self.entered is not None:
            self.entered.set()
        if self.release is not None:
            assert self.release.wait(5), "The test did not release the application."
        return self.project

    def open_project(self, path: Path) -> None:
        self.calls.append(("open", path))
        if self.failure is not None:
            raise self.failure

    def save_project(self, path: Path) -> None:
        self.calls.append(("save", path))
        if self.failure is not None:
            raise self.failure
        path.write_text("Saved test project")

    def close_project(self) -> None:
        self.calls.append(("close_project", None))

    def disconnect(self) -> None:
        self.calls.append(("disconnect", None))

    def terminate(self) -> None:
        self.calls.append(("terminate", None))


class FactoryDouble:
    def __init__(self) -> None:
        self.apps = {port: ApplicationDouble(port) for port in (50051, 50052)}
        self.calls: list[str] = []

    def launch(self, executable: Path) -> ApplicationDouble:
        self.calls.append("launch")
        return self.apps[50051]

    def attach(self, endpoint: Endpoint) -> ApplicationDouble:
        self.calls.append("attach")
        return self.apps[endpoint.port]

"""Controlled native fixtures test coordination, not real application acceptance."""

from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

from PIL import Image

from resinsight_mcp.contracts.errors import ContractError, Error
from resinsight_mcp.contracts.observations import ViewContext
from resinsight_mcp.contracts.sessions import Endpoint, ObjectKind, ProcessIdentity
from resinsight_mcp.resinsight.sessions._backend import (
    ApplicationAccess,
    NativeObject,
    ProjectSnapshot,
)
from resinsight_mcp.resinsight.views._backend import NativeViewState


@dataclass
class ControlledApplication:
    endpoint: Endpoint = field(default_factory=lambda: Endpoint(port=50051))
    process: ProcessIdentity = field(
        default_factory=lambda: ProcessIdentity(pid=1234, start_marker=uuid4().hex)
    )

    def verify_process(self) -> ProcessIdentity:
        return self.process

    def snapshot(self) -> ProjectSnapshot:
        return ProjectSnapshot(
            root_address="project",
            objects=(
                NativeObject(kind=ObjectKind.CASE, address="case", name="Case"),
                NativeObject(kind=ObjectKind.VIEW, address="view", name="View"),
                NativeObject(kind=ObjectKind.WELL, address="well", name="Well"),
                NativeObject(kind=ObjectKind.VIEW, address="other-view", name="Other view"),
            ),
        )

    def open_project(self, path: Path) -> None:
        raise AssertionError("This fixture does not open projects.")

    def save_project(self, path: Path) -> None:
        raise AssertionError("This fixture does not save projects.")

    def close_project(self) -> None:
        raise AssertionError("This fixture does not close projects.")

    def disconnect(self) -> None:
        pass

    def terminate(self) -> None:
        raise AssertionError("This fixture does not terminate processes.")


@dataclass
class ControlledFactory:
    application: ControlledApplication

    def attach(self, endpoint: Endpoint) -> ControlledApplication:
        assert endpoint == self.application.endpoint
        return self.application

    def launch(self, executable: Path) -> ControlledApplication:
        raise AssertionError("This fixture does not launch processes.")


@dataclass
class ControlledView:
    current: ViewContext | None = None
    edit_error: Error | None = None
    export_error: Error | None = None
    missing_export: bool = False

    def validate(self, context: ViewContext) -> None:
        pass

    def apply(self, context: ViewContext) -> ViewContext:
        if self.edit_error is not None:
            raise ContractError(self.edit_error)
        self.current = context
        return context

    def inspect(self, context: ViewContext) -> ViewContext:
        assert self.current is not None
        return self.current

    def export(self, folder: Path, width: int, height: int) -> None:
        if self.export_error is not None:
            raise ContractError(self.export_error)
        if not self.missing_export:
            Image.new("RGB", (width, height), "navy").save(folder / "native.png")


@dataclass
class ControlledBackend:
    native: ControlledView
    selections: list[tuple[NativeObject, ...]] = field(default_factory=list)
    discovered: tuple[NativeViewState, ...] = ()

    def list_views(
        self, access: ApplicationAccess, case_address: str
    ) -> tuple[NativeViewState, ...]:
        return self.discovered

    def select(self, access: ApplicationAccess, context: ViewContext) -> ControlledView:
        self.selections.append(access.objects)
        return self.native

"""Verify the supported file-backed load and geometry checks without a native process."""

from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from resinsight_mcp.contracts.errors import ContractError, ErrorCode
from resinsight_mcp.contracts.sessions import ProjectState
from resinsight_mcp.models.imports import MaterializedModel, OpmImportService
from resinsight_mcp.resinsight.sessions._backend import ApplicationAccess
from resinsight_mcp.resinsight.sessions.rips import RipsApplication
from resinsight_mcp.resinsight.wells import RipsWellBackend

from ._support import Harness, harness

__all__ = ["harness"]


class PreparedApplication(RipsApplication):
    def __init__(self, materialized: MaterializedModel) -> None:
        self.events: list[str] = []
        self.materialized = materialized
        inspection = materialized.inspection
        self.corners = [
            SimpleNamespace(
                **{
                    f"c{corner}": SimpleNamespace(x=float(index), y=float(corner), z=depth)
                    for corner in range(8)
                }
            )
            for index, depth in enumerate(inspection.cell_depths_ft)
        ]
        self.active = [
            SimpleNamespace(grid_index=0, local_ijk=SimpleNamespace(i=cell.i, j=cell.j, k=cell.k))
            for cell in inspection.active_cells
        ]
        self.properties = dict(inspection.properties.keyword_arrays())
        self.properties["riCELLVOLUME"] = inspection.cell_volumes_ft3
        ni, nj, nk = inspection.summary.dimensions
        self.case = SimpleNamespace(
            id=0,
            address=lambda: 1,
            file_path=str(materialized.directory.parent / "grid.EGRID"),
            create_view=lambda: self.events.append("view"),
            import_properties=self.import_properties,
            available_properties=lambda category: list(self.properties),
            active_cell_property=lambda category, name, report: self.properties[name],
            cell_info_for_active_cells=lambda: self.active,
            grid=lambda: SimpleNamespace(
                dimensions=lambda: SimpleNamespace(i=ni, j=nj, k=nk),
                cell_centers=lambda: [
                    SimpleNamespace(z=value) for value in inspection.cell_depths_ft
                ],
                cell_corners=lambda: self.corners,
            ),
        )

    def import_properties(self, file_names: list[str]) -> SimpleNamespace:
        assert file_names == [str(self.materialized.property_file)]
        self.events.append("properties")
        return SimpleNamespace(
            values=[name for name, _ in self.materialized.inspection.properties.keyword_arrays()]
        )

    def call[T](self, action: Callable[[], T], *, mutation: bool = False) -> T:
        return action()

    def export(self, path: str, output_path: str) -> None:
        assert path == str(self.materialized.entrypoint)
        assert output_path == self.case.file_path
        self.events.append("export")
        Path(output_path).write_text("Controlled exported grid.")

    def load(self, path: str, grid_only: bool) -> Any:
        assert path == self.case.file_path and grid_only
        self.events.append("load")
        return self.case

    def project(self) -> Any:
        return SimpleNamespace(
            export_prepared_input_grid=self.export,
            load_case=self.load,
            cases=lambda: [self.case],
        )


def test_prepared_load_exports_then_loads_properties_and_creates_a_view(
    harness: Harness, tmp_path: Path
) -> None:
    materialized = OpmImportService(harness.store).materialize_persistent(
        harness.binding.model, tmp_path / "native-backend"
    )
    application = PreparedApplication(materialized)
    access = ApplicationAccess(application, ProjectState(context=harness.binding.case.context), ())
    backend = RipsWellBackend()
    assert backend.load(access, materialized) == "1"
    assert application.events == ["export", "load", "properties", "view"]
    corners = backend.case_geometry(access, "1", materialized)
    assert len(corners) == 24 * 300
    backend.verify_case(access, "1", materialized, corners)
    application.corners[123].c7.x += 1.0
    with pytest.raises(ContractError, match="corner geometry"):
        backend.verify_case(access, "1", materialized, corners)


@pytest.mark.parametrize("change", ["path", "active-order", "property", "missing-corner"])
def test_restored_case_rejects_wrong_source_or_model_data(
    harness: Harness, tmp_path: Path, change: str
) -> None:
    materialized = OpmImportService(harness.store).materialize_persistent(
        harness.binding.model, tmp_path / "native-backend"
    )
    application = PreparedApplication(materialized)
    access = ApplicationAccess(application, ProjectState(context=harness.binding.case.context), ())
    backend = RipsWellBackend()
    backend.load(access, materialized)
    corners = backend.case_geometry(access, "1", materialized)
    if change == "path":
        application.case.file_path = str(tmp_path / "another.EGRID")
    elif change == "active-order":
        application.active.reverse()
    elif change == "property":
        application.properties["PERMX"] = (99.0,) * 300
    else:
        application.corners.pop()
    with pytest.raises(ContractError) as rejected:
        backend.verify_case(access, "1", materialized, corners)
    assert rejected.value.error.code == ErrorCode.STALE_OBJECT

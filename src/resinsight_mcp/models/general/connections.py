"""Read issued native connections without requiring a running native application."""

from collections.abc import Iterator
from itertools import islice
from typing import Literal

from pydantic import PositiveInt

from resinsight_mcp.contracts._base import Record
from resinsight_mcp.contracts.engineering import CellIndex, ModelRef
from resinsight_mcp.contracts.models import ArtifactRef
from resinsight_mcp.contracts.wells import WellStatus

from .arrays import fail, value
from .records import NamedArray
from .wells import GeneralConnection, GeneralWellhead, GeneralWellModels


class GeneralWellConnections(Record):
    artifact: ArtifactRef
    version: Literal["general-connections-v1"] = "general-connections-v1"
    well_receipt: ArtifactRef
    plan: ArtifactRef
    model: ModelRef
    wellhead: GeneralWellhead
    length_unit: Literal["m", "ft"]
    count: PositiveInt
    measured_depth_semantics: str = (
        "Native aggregate bounds can span gaps between intervals in one cell."
    )
    columns: tuple[NamedArray, ...]


class ConnectionStorage:
    def __init__(self, plans: GeneralWellModels) -> None:
        self.plans, self.arrays = plans, plans.arrays

    def read(self, reference: ArtifactRef) -> GeneralWellConnections:
        with self.arrays.store.open_artifact(reference) as stream:
            result = GeneralWellConnections.model_validate_json(stream.read())
        refs = (result.plan, result.well_receipt, *(c.array.artifact for c in result.columns))
        if (
            result.artifact != reference
            or result.model.session_id != reference.session_id
            or any(ref.session_id != reference.session_id for ref in refs)
        ):
            fail("The saved connections belong to another artifact or session.")
        plan = value(self.plans.inspect(result.plan))
        if plan.model != result.model or plan.length_unit != result.length_unit:
            fail("The saved connections differ from their well plan or model units.")
        unit = result.length_unit
        convention = "ECLIPSE_METRIC_COMPDAT" if unit == "m" else "ECLIPSE_FIELD_COMPDAT"
        expected = (
            ("cells", "int64", "zero_based_ijk", 3),
            ("factor", "float64", convention, 1),
            ("kh", "float64", f"mD*{unit}", 1),
            ("diameter", "float64", unit, 1),
            ("skin", "float64", "1", 1),
            ("direction", "int64", "X=1,Y=2,Z=3", 1),
            ("status", "int64", "SHUT=0,OPEN=1", 1),
            ("measured_depth", "float64", unit, 2),
        )
        actual = tuple((c.name, c.array.dtype, c.array.unit, c.array.count) for c in result.columns)
        if actual != tuple(
            (name, dtype, unit, width * result.count) for name, dtype, unit, width in expected
        ):
            fail("The connection columns differ from the supported export schema.")
        for column in result.columns:
            if self.arrays.descriptor(column.array.artifact).info() != column.array:
                fail("A connection column differs from its stored array descriptor.")
        return result

    def rows(self, export: GeneralWellConnections) -> Iterator[GeneralConnection]:
        self.arrays.policy.require_memory(
            sum(
                max(c.count for c in self.arrays.descriptor(column.array.artifact).chunks)
                for column in export.columns
            )
            * 16
            / 1024**2
        )

        def values(index: int) -> Iterator[float]:
            for part in self.arrays.chunks(export.columns[index].array.artifact):
                yield from (float(v) for v in part)

        streams = [values(index) for index in range(len(export.columns))]
        for _ in range(export.count):
            cell = tuple(int(v) for v in islice(streams[0], 3))
            factor, kh, diameter, skin, direction, status = (
                next(stream) for stream in streams[1:7]
            )
            start, end = islice(streams[7], 2)
            if direction not in (1, 2, 3) or status not in (0, 1):
                fail("A connection has an unsupported direction or status code.")
            yield GeneralConnection(
                cell=CellIndex(i=cell[0], j=cell[1], k=cell[2]),
                factor=factor,
                kh=kh,
                diameter=diameter,
                skin=skin,
                direction=("X", "Y", "Z")[int(direction) - 1],
                status=WellStatus.OPEN if status else WellStatus.SHUT,
                start_md=start,
                end_md=end,
            )

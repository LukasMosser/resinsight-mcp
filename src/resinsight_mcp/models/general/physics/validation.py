"""Validate table values in bounded blocks without materializing entire columns."""

from collections.abc import Iterator

from resinsight_mcp.models.general.arrays import ArrayService, fail

from .records import TableInfo


def rows(arrays: ArrayService, table: TableInfo) -> Iterator[tuple[float, ...]]:
    arrays.policy.require_memory(
        sum(
            max(chunk.count for chunk in arrays.descriptor(c.array.artifact).chunks)
            for c in table.columns
        )
        * 16
        / 1024**2
    )

    def values(index: int) -> Iterator[float]:
        for part in arrays.chunks(table.columns[index].array.artifact):
            yield from (float(value) for value in part)

    yield from zip(*(values(index) for index in range(len(table.columns))), strict=True)


def require(condition: bool, table: TableInfo, rule: str) -> None:
    if not condition:
        fail(f"{table.keyword} region {table.region}: {rule}")


def ordinary_row(table: TableInfo, row: tuple[float, ...]) -> None:
    values = {column.name: value for column, value in zip(table.columns, row, strict=True)}
    positive = {"pressure", "datum_pressure", "volume_factor", "viscosity", "oil", "water", "gas"}
    nonnegative = {"compressibility", "solution_ratio"}
    for name, value in values.items():
        if name in positive:
            require(value > 0, table, f"{name} must be positive.")
        if name in nonnegative:
            require(value >= 0, table, f"{name} must be nonnegative.")
        if name == "saturation" or name.endswith("_relperm"):
            require(0 <= value <= 1, table, f"{name} must be within [0, 1].")
    if table.keyword == "EQUIL":
        require(
            row[4] <= row[2], table, "The gas contact must not be deeper than the water contact."
        )
        require(row[6:] == (1, 0, 0), table, "The selected profile requires flags 1, 0, 0.")


def validate_values(arrays: ArrayService, table: TableInfo) -> None:
    previous: tuple[float, ...] | None = None
    bubble_pressure = float("-inf")
    branches = 0
    for row in rows(arrays, table):
        ordinary_row(table, row)
        if table.keyword == "PVTO":
            new_branch = previous is None or row[0] != previous[0]
            if new_branch:
                require(row[1] > bubble_pressure, table, "Bubble pressures must increase.")
                bubble_pressure = row[1]
                branches += 1
            if previous is not None:
                require(row[0] >= previous[0], table, "Solution ratios must not decrease.")
                if not new_branch:
                    require(
                        row[1] > previous[1], table, "Pressure must increase within each branch."
                    )
        elif previous is not None:
            require(row[0] > previous[0], table, "The first column must increase strictly.")
        previous = row
    if table.keyword == "PVTO":
        require(branches >= 2, table, "At least two solution-ratio branches are required.")

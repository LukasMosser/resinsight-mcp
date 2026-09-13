"""One source for supported table columns, simulator units, and region ownership."""

from .records import ColumnSchema, Keyword, PhysicsSchema, RegionKeyword, SchemaRequest, TableSchema

GROUPS: dict[RegionKeyword, tuple[Keyword, ...]] = {
    "PVTNUM": ("PVTW", "ROCK", "DENSITY", "PVDG", "PVTO"),
    "SATNUM": ("SWOF", "SGOF"),
    "EQLNUM": ("EQUIL", "RSVD"),
}


def schema(request: SchemaRequest) -> PhysicsSchema:
    metric = request.unit_system == "METRIC"
    pressure, length = ("bar", "m") if metric else ("psia", "ft")
    density = "kg/m3" if metric else "lb/ft3"
    liquid_fvf = "rm3/sm3" if metric else "rb/stb"
    gas_fvf = "rm3/sm3" if metric else "rb/Mscf"
    ratio = "sm3/sm3" if metric else "Mscf/stb"

    def table(
        keyword: Keyword,
        columns: tuple[tuple[str, str], ...],
        minimum: int,
        single: bool,
        rules: str,
    ) -> TableSchema:
        return TableSchema(
            keyword=keyword,
            region_keyword=next(group for group, keys in GROUPS.items() if keyword in keys),
            columns=tuple(
                ColumnSchema(
                    name=name, unit=unit, dtype="int64" if name.endswith("_flag") else "float64"
                )
                for name, unit in columns
            ),
            minimum_rows=minimum,
            single_row=single,
            rules=rules,
        )

    return PhysicsSchema(
        unit_system=request.unit_system,
        tables=(
            table(
                "PVTW",
                (
                    ("pressure", pressure),
                    ("volume_factor", liquid_fvf),
                    ("compressibility", f"1/{pressure}"),
                    ("viscosity", "cP"),
                    ("viscosibility", f"1/{pressure}"),
                ),
                1,
                True,
                "Positive pressure, volume factor, and viscosity. Nonnegative compressibility.",
            ),
            table(
                "ROCK",
                (("pressure", pressure), ("compressibility", f"1/{pressure}")),
                1,
                True,
                "Positive reference pressure and nonnegative compressibility.",
            ),
            table(
                "DENSITY",
                (("oil", density), ("water", density), ("gas", density)),
                1,
                True,
                "All surface densities are positive.",
            ),
            table(
                "PVDG",
                (("pressure", pressure), ("volume_factor", gas_fvf), ("viscosity", "cP")),
                2,
                False,
                "Pressure increases strictly. All values are positive.",
            ),
            table(
                "PVTO",
                (
                    ("solution_ratio", ratio),
                    ("pressure", pressure),
                    ("volume_factor", liquid_fvf),
                    ("viscosity", "cP"),
                ),
                2,
                False,
                "Equal solution ratios form one branch. Ratios and branch pressures increase. "
                "Bubble pressures increase between branches. At least two branches are required.",
            ),
            table(
                "SWOF",
                (
                    ("saturation", "1"),
                    ("water_relperm", "1"),
                    ("oil_relperm", "1"),
                    ("capillary_pressure", pressure),
                ),
                2,
                False,
                "Saturation increases strictly. "
                "Saturation and relative permeability are within [0, 1].",
            ),
            table(
                "SGOF",
                (
                    ("saturation", "1"),
                    ("gas_relperm", "1"),
                    ("oil_relperm", "1"),
                    ("capillary_pressure", pressure),
                ),
                2,
                False,
                "Saturation increases strictly. "
                "Saturation and relative permeability are within [0, 1].",
            ),
            table(
                "EQUIL",
                (
                    ("datum_depth", length),
                    ("datum_pressure", pressure),
                    ("water_oil_contact", length),
                    ("water_oil_capillary_pressure", pressure),
                    ("gas_oil_contact", length),
                    ("gas_oil_capillary_pressure", pressure),
                    ("black_oil_flag", "1"),
                    ("wet_gas_flag", "1"),
                    ("accuracy_flag", "1"),
                ),
                1,
                True,
                "Positive datum pressure. Gas contact is no deeper than water contact. "
                "This profile requires explicit flags 1, 0, 0 and an RSVD table.",
            ),
            table(
                "RSVD",
                (("depth", length), ("solution_ratio", ratio)),
                2,
                False,
                "Depth increases strictly and solution ratios are nonnegative.",
            ),
        ),
    )

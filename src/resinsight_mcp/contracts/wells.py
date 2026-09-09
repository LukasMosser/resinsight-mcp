"""Shared FIELD well controls for authored model changes."""

from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import Field, NonNegativeFloat, PositiveFloat, StringConstraints, model_validator

from ._base import Record

type WellName = Annotated[
    str, StringConstraints(min_length=1, max_length=8, pattern=r"^[A-Za-z][A-Za-z0-9_]*$")
]


class WellStatus(StrEnum):
    OPEN = "OPEN"
    SHUT = "SHUT"


class FieldSurfaceRate(Record):
    """A volume rate at surface conditions in FIELD units."""

    value: NonNegativeFloat
    unit: Literal["stb/day", "Mscf/day"]


class ProducerControl(Record):
    kind: Literal["producer"] = "producer"
    status: WellStatus
    mode: Literal["ORAT", "BHP"]
    oil_rate: FieldSurfaceRate | None = None
    bhp_psia: PositiveFloat

    @model_validator(mode="after")
    def check_rate(self) -> Self:
        if self.mode == "BHP":
            if self.oil_rate is not None:
                raise ValueError("BHP control forbids an oil rate.")
        else:
            if self.oil_rate is None or self.oil_rate.unit != "stb/day":
                raise ValueError("ORAT control requires an oil rate in stb/day.")
            if self.status == WellStatus.OPEN and self.oil_rate.value <= 0:
                raise ValueError("OPEN control requires a positive oil rate.")
        return self


class InjectorControl(Record):
    kind: Literal["injector"] = "injector"
    status: WellStatus
    phase: Literal["WATER", "GAS"]
    mode: Literal["RATE", "BHP"]
    surface_rate: FieldSurfaceRate | None = None
    bhp_psia: PositiveFloat

    @model_validator(mode="after")
    def check_rate(self) -> Self:
        if self.mode == "BHP":
            if self.surface_rate is not None:
                raise ValueError("BHP control forbids a surface rate.")
        else:
            unit = "stb/day" if self.phase == "WATER" else "Mscf/day"
            if self.surface_rate is None or self.surface_rate.unit != unit:
                raise ValueError(f"RATE control for {self.phase} requires a rate in {unit}.")
            if self.status == WellStatus.OPEN and self.surface_rate.value <= 0:
                raise ValueError("OPEN control requires a positive surface rate.")
        return self


type WellControl = Annotated[ProducerControl | InjectorControl, Field(discriminator="kind")]

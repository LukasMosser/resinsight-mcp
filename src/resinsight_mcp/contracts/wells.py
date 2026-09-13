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


def require_control_rate(
    status: WellStatus, mode: str, rate: tuple[float, str] | None, unit: str
) -> None:
    """Apply the same rate and pressure rules to all authored controls."""
    if mode == "BHP":
        if rate is not None:
            raise ValueError("BHP control forbids a rate target.")
    elif rate is None or rate[1] != unit:
        raise ValueError(f"{mode} control requires a rate in {unit}.")
    elif status == WellStatus.OPEN and rate[0] <= 0:
        raise ValueError("OPEN control requires a positive rate.")


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
        require_control_rate(
            self.status,
            self.mode,
            None if self.oil_rate is None else (self.oil_rate.value, self.oil_rate.unit),
            "stb/day",
        )
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
        require_control_rate(
            self.status,
            self.mode,
            None
            if self.surface_rate is None
            else (self.surface_rate.value, self.surface_rate.unit),
            "stb/day" if self.phase == "WATER" else "Mscf/day",
        )
        return self


type WellControl = Annotated[ProducerControl | InjectorControl, Field(discriminator="kind")]

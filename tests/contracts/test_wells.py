"""Authored well controls preserve explicit rates, phases, and pressure limits."""

import json

import pytest
from pydantic import TypeAdapter, ValidationError

from resinsight_mcp.contracts.wells import (
    FieldSurfaceRate,
    InjectorControl,
    ProducerControl,
    WellControl,
    WellName,
    WellStatus,
)

CONTROL = TypeAdapter(WellControl)


@pytest.mark.parametrize("status", list(WellStatus))
@pytest.mark.parametrize(
    "fields",
    [
        {"kind": "producer", "mode": "ORAT", "oil_rate": {"value": 100.0, "unit": "stb/day"}},
        {"kind": "producer", "mode": "BHP"},
        {
            "kind": "injector",
            "phase": "WATER",
            "mode": "RATE",
            "surface_rate": {"value": 100.0, "unit": "stb/day"},
        },
        {
            "kind": "injector",
            "phase": "GAS",
            "mode": "RATE",
            "surface_rate": {"value": 100.0, "unit": "Mscf/day"},
        },
        {"kind": "injector", "phase": "WATER", "mode": "BHP"},
        {"kind": "injector", "phase": "GAS", "mode": "BHP"},
    ],
)
def test_controls_round_trip_through_discriminated_json(
    status: WellStatus, fields: dict[str, object]
) -> None:
    control = CONTROL.validate_python({**fields, "status": status, "bhp_psia": 3000.0})
    assert CONTROL.validate_json(CONTROL.dump_json(control)) == control
    assert control.status == status
    assert control.bhp_psia == 3000.0
    assert isinstance(control, ProducerControl if fields["kind"] == "producer" else InjectorControl)


@pytest.mark.parametrize(
    ("kind", "rate_field", "phase", "unit"),
    [
        ("producer", "oil_rate", None, "stb/day"),
        ("injector", "surface_rate", "WATER", "stb/day"),
        ("injector", "surface_rate", "GAS", "Mscf/day"),
    ],
)
def test_rate_modes_require_matching_rates_and_allow_zero_only_when_shut(
    kind: str, rate_field: str, phase: str | None, unit: str
) -> None:
    payload: dict[str, object] = {
        "kind": kind,
        "mode": "ORAT" if kind == "producer" else "RATE",
        "status": WellStatus.SHUT,
        "bhp_psia": 3000.0,
        rate_field: {"value": 0.0, "unit": unit},
    }
    if phase is not None:
        payload["phase"] = phase
    assert CONTROL.validate_python(payload).status == WellStatus.SHUT
    for change in (
        {"status": WellStatus.OPEN},
        {rate_field: None},
        {rate_field: {"value": 10.0, "unit": "Mscf/day" if unit == "stb/day" else "stb/day"}},
        {"mode": "BHP"},
    ):
        with pytest.raises(ValidationError):
            CONTROL.validate_python({**payload, **change})
    del payload[rate_field]
    with pytest.raises(ValidationError):
        CONTROL.validate_python(payload)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), -1.0, "10", True])
def test_surface_rates_reject_invalid_numbers(value: object) -> None:
    with pytest.raises(ValidationError):
        FieldSurfaceRate.model_validate({"value": value, "unit": "stb/day"})


@pytest.mark.parametrize(
    "value", [float("nan"), float("inf"), float("-inf"), 0.0, -1.0, "10", True]
)
@pytest.mark.parametrize("kind", ["producer", "injector"])
def test_pressure_limits_require_positive_finite_numbers(value: object, kind: str) -> None:
    payload = {"kind": kind, "status": WellStatus.SHUT, "mode": "BHP", "bhp_psia": value}
    if kind == "injector":
        payload["phase"] = "GAS"
    with pytest.raises(ValidationError):
        CONTROL.validate_python(payload)


@pytest.mark.parametrize(
    "change",
    [{"kind": "other"}, {"mode": "WRAT"}, {"status": "AUTO"}, {"extra": 1}],
)
def test_controls_reject_unknown_choices_and_fields(change: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        CONTROL.validate_json(
            json.dumps(
                {"kind": "producer", "status": "OPEN", "mode": "BHP", "bhp_psia": 3000, **change}
            )
        )


def test_injector_rejects_oil_phase_and_surface_rate_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        InjectorControl.model_validate(
            {"status": WellStatus.OPEN, "phase": "OIL", "mode": "BHP", "bhp_psia": 3000.0}
        )
    with pytest.raises(ValidationError):
        FieldSurfaceRate.model_validate({"value": 10.0, "unit": "stb/day", "extra": 1})
    with pytest.raises(ValidationError):
        FieldSurfaceRate.model_validate({"value": 10.0, "unit": "m3/day"})


@pytest.mark.parametrize("name", ["A", "Prod_123", "abcdefgh", "Z9"])
def test_authored_well_names_round_trip(name: str) -> None:
    adapter = TypeAdapter(WellName)
    assert adapter.validate_json(adapter.dump_json(adapter.validate_python(name))) == name


@pytest.mark.parametrize("name", ["", "123", "_PROD", "ABCDEFGHI", "A-B", "Å", "A\n", "A*", 1])
def test_authored_well_names_reject_invalid_names(name: object) -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(WellName).validate_python(name, strict=True)

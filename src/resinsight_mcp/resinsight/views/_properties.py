"""Supported native properties retain the trusted input unit system."""

from resinsight_mcp.contracts.engineering import Unit, UnitSystem
from resinsight_mcp.contracts.errors import ContractError, Error, ErrorCode
from resinsight_mcp.contracts.models import ModelRevision
from resinsight_mcp.contracts.observations import ViewContext

PROPERTY_CATEGORIES = {
    "PRESSURE": "DYNAMIC_NATIVE",
    "SWAT": "DYNAMIC_NATIVE",
    "SGAS": "DYNAMIC_NATIVE",
    "SOIL": "DYNAMIC_NATIVE",
    "PORO": "STATIC_NATIVE",
}
_PRESSURE_UNITS = {UnitSystem.FIELD: Unit.PSI}


def require_units(context: ViewContext, revision: ModelRevision) -> None:
    if context.coordinates != revision.coordinates:
        raise ContractError(
            Error(
                code=ErrorCode.INVALID_MODEL,
                message="The view coordinates differ from the stored input revision.",
            )
        )
    name = context.property.name
    if name not in PROPERTY_CATEGORIES:
        raise ContractError(
            Error(
                code=ErrorCode.UNSUPPORTED_OPERATION,
                message="Supported view properties are PRESSURE, SWAT, SGAS, SOIL, and PORO.",
            )
        )
    expected = _PRESSURE_UNITS.get(revision.unit_system) if name == "PRESSURE" else Unit.ONE
    if expected is None:
        raise ContractError(
            Error(
                code=ErrorCode.UNSUPPORTED_OPERATION,
                message="Native pressure display currently supports proved FIELD input units.",
            )
        )
    if context.property.unit != expected:
        raise ContractError(
            Error(
                code=ErrorCode.INVALID_MODEL,
                message="The property unit differs from the stored input unit system.",
            )
        )

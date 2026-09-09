"""Run metadata preserves the exact staged model and reserved output identities."""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from resinsight_mcp.contracts.engineering import CoordinateFrame, ModelRef
from resinsight_mcp.contracts.identifiers import GridId, ResultId
from resinsight_mcp.contracts.models import ArtifactRef
from resinsight_mcp.contracts.results import ResultOutput
from resinsight_mcp.models.imports import ModelInspection

SATURATION_BOUND_TOLERANCE = 2.384185791015625e-7


class FlowRunRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    model: ModelRef
    coordinates: CoordinateFrame
    result_id: ResultId
    grid_id: GridId
    directory: Path
    entrypoint: str
    inspection: ModelInspection
    outputs: tuple[ResultOutput, ...]
    numerical_data: ArtifactRef
    assessment_evidence: ArtifactRef
    expected_program_version: str


class SemanticArray(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)
    name: str
    unit: str
    values: tuple[float | str | bool, ...]


class FlowAssessment(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)
    policy: Literal["opm-field-validity-v1"] = "opm-field-validity-v1"
    expected_program_version: str
    observed_program_version: str
    final_simulated_days: float
    expected_simulated_days: float
    warnings: tuple[str, ...]
    input_and_output_identity_verified: bool
    initial_arrays: tuple[SemanticArray, ...]
    summary_arrays: tuple[SemanticArray, ...]
    numerical_reference_assessed: bool = False
    saturation_bound_tolerance: float = SATURATION_BOUND_TOLERANCE
    tolerance_rule: str = (
        "Reference comparisons use two representable output increments at the largest "
        "reference magnitude, with zero relative tolerance. Collection does not perform "
        "an independent reference comparison."
    )

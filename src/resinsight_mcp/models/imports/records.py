"""Public records for the bounded OPM import service."""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, PositiveInt

from resinsight_mcp.contracts.engineering import ModelRef
from resinsight_mcp.contracts.identifiers import SessionId
from resinsight_mcp.contracts.models import ArtifactRef, PreparedModel


class ImportRequest(BaseModel):
    """Import files below one trusted local directory without editing them."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    session_id: SessionId
    source_root: Path
    entrypoint: str
    datum: str


class IncludeEdge(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    source: str
    target: str


class ModelSummary(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    parser_version: Literal["2025.10"] = "2025.10"
    support_profile: Literal["spe1-field-v1"] = "spe1-field-v1"
    unit_system: Literal["FIELD"] = "FIELD"
    dimensions: tuple[PositiveInt, PositiveInt, PositiveInt]
    active_cells: PositiveInt
    wells: tuple[str, ...]
    report_steps: PositiveInt
    elapsed_days: float
    keywords: tuple[str, ...]


class ImportReceipt(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    prepared: PreparedModel
    record: ArtifactRef
    summary: ModelSummary


class ImportRecord(BaseModel):
    """Source artifacts belong to the revision and changes stay separate."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    model: ModelRef
    source_entrypoint: str
    sources: dict[str, ArtifactRef]
    includes: tuple[IncludeEdge, ...]
    changes: tuple[()] = ()
    summary: ModelSummary

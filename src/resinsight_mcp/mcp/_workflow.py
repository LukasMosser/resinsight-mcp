"""Compose the bounded OPM workflow only after its local dependencies pass."""

from pathlib import Path

from resinsight_mcp.models.imports import OpmImportService
from resinsight_mcp.models.synthetic import SyntheticModelService
from resinsight_mcp.models.wells.service import OpmWellScheduleService
from resinsight_mcp.resinsight.sessions import ResInsightSessionService
from resinsight_mcp.resinsight.views import ResInsightViewService
from resinsight_mcp.results import ResultsService
from resinsight_mcp.simulators.opm import FlowConfiguration, OpmFlowService
from resinsight_mcp.workspaces import SqliteWorkspaceStore

from .catalog import Bindings
from .launcher import ConfigurationError


def check_dependencies(docker_executable: Path | None) -> FlowConfiguration:
    """Check generated client interfaces and the pinned local image without launching."""
    try:
        import rips
    except (ImportError, OSError) as error:
        raise ConfigurationError(
            f"Cannot import the required generated RIPS client: {error}"
        ) from error
    required = {
        "Project": ("export_prepared_input_grid",),
        "WellPathCollection": ("create_modeled_well_path_for_case",),
        "WellPath": ("completion_data", "trajectory_properties"),
        "ModeledWellPath": ("well_path_geometry",),
        "View": ("set_camera_projection", "validate_view_controls", "export_snapshot"),
        "SummaryPlotCollection": ("new_summary_plot",),
        "Plot": ("export_snapshot",),
        "SummaryCase": ("available_time_steps", "summary_vector_values"),
    }
    missing = [
        f"{name}.{method}"
        for name, methods in required.items()
        for method in methods
        if not callable(getattr(getattr(rips, name, None), method, None))
    ]
    if missing:
        raise ConfigurationError(
            "The OPM workflow requires the matching generated RIPS client. "
            f"Missing interfaces: {', '.join(missing)}."
        )
    configuration = (
        FlowConfiguration(docker=docker_executable)
        if docker_executable is not None
        else FlowConfiguration()
    )
    configuration.check_dependencies()
    return configuration


def workflow_bindings(
    root: Path,
    workspaces: SqliteWorkspaceStore,
    sessions: ResInsightSessionService,
    configuration: FlowConfiguration,
) -> Bindings:
    """Keep application ownership, input publication, and validation in their services."""
    from resinsight_mcp.resinsight.views.rips import RipsViewBackend
    from resinsight_mcp.resinsight.wells import ResInsightWellService, RipsWellBackend
    from resinsight_mcp.results.rips import RipsResultBackend

    imports = OpmImportService(workspaces)
    wells = ResInsightWellService(
        workspaces, sessions, imports, RipsWellBackend(), source_root=root / "native-models"
    )
    flow = OpmFlowService(root, configuration)
    views = ResInsightViewService(workspaces, sessions, RipsViewBackend())
    results = ResultsService(
        workspaces, sessions, views, RipsResultBackend(), root / "native-results", flow
    )
    return Bindings(
        workspaces=workspaces,
        sessions=sessions,
        imports=imports,
        synthetic_models=SyntheticModelService(workspaces),
        wells=wells,
        schedules=OpmWellScheduleService(imports, wells),
        jobs=flow,
        flow=flow,
        results=results,
        views=views,
        renderer=views,
    )

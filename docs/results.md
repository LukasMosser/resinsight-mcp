# Accepted results

`ResultsService` reads accepted simulator results and connects them to native ResInsight cases and summary plots.
A result is an immutable record of one completed job and its exact model revision.
An immutable record cannot change after storage.
Every request retains an explicit workspace session, result, model revision, and job identity where required.
An accepted result does not establish agreement with an independent numerical reference.

## Requirements and identity

Use an accepted stored result with its complete output manifest.
A manifest identifies the result files and numerical data.
The service rejects rejected results, missing manifests, and numerical data that disagree with the stored identity.
The configured output verifier checks materialized files against their immutable collected references.
Changing identifiers in a request does not create a new result or authorize another session.

Native operations require configured session and view services, a result backend, and a compatible ResInsight application with its matching RIPS client.
RIPS is the Python client for ResInsight remote calls.
The [developer guide](development/results.md) describes service configuration, verification rules, and evidence.
The maintained tests cover queries, comparisons, binding failures, and image outcomes through controlled native interfaces.
Those tests do not establish completed native application acceptance.

## Load and query

Call `load(ResultImportRequest)` with the current application context, exact stored job, and accepted result.
The service preserves all five result files at stable paths, loads a grid case, creates its view, and imports a summary case.
It verifies native values and geometry before binding the case to the result.
The grid case name includes the result and model revision identifiers.
Keep the materialized files at their original paths while a saved native project refers to them.

Call `cell_property(CellQuery)` for one property at an exact report time.
The response contains the complete result, active cell order, geometry, unit, report time, and values.
Call `curve(CurveQuery)` for a field or well summary curve.
The response contains the complete result, curve identity, unit, report times, and values.
These queries read stored numerical data without launching ResInsight or a simulator.

Pressure uses `psi`, and saturation uses the dimensionless unit `1`.
Field oil rate uses stock tank barrels per day.
Report records retain their index, elapsed days, and calendar date.
Use the report records from the stored result instead of constructing approximate dates or indices.
Native values must agree with the accepted source values and their verified source units.
The RIPS interface does not provide an independent native unit read for these operations.

## Compare results

Call `compare_cells(baseline_query, scenario_query)` to obtain scenario values minus baseline values.
Cell comparisons require matching geometry, coordinate frames, active cell order, quantities, units, and report times within one session.
Separate runs can have different grid identifiers when their complete geometry matches.
The response retains both source records and one legend covering both value arrays.

Apply that returned legend to both native views before capturing comparison images.
Keep the camera and report time consistent across both views.
The [view guide](views.md) describes complete view requests and image receipts.

Call `compare_curves(baseline_query, scenario_query)` for aligned field or well curves.
Both curves must use the same session, quantity, well identity, units, and report times.
The service does not interpolate values or convert units for comparison.

## Summary plots and receipts

Call `show_curve(SummaryPlotRequest)` to create a native plot for an exact stored curve.
The plot title includes the result identifier, quantity, and unit, with normalization disabled.
The response contains `EditedSummaryPlot`, which separates confirmed plot creation from the image outcome.
Its applied receipt retains the current application context, complete curve, and native plot address.

A failed image does not undo a confirmed plot.
Image persistence or delivery failures remain inside `EditedSummaryPlot.observation` while the applied receipt remains available.
An unconfirmed native creation returns an outer failure with an uncertain effect instead of an applied receipt.
The service never substitutes an earlier image for a failed capture.
Make sure that the nested observation succeeds before using its image as evidence.

This typed example uses an existing configured service, result, job, and current application context.
It loads one result, queries producer pressure, and handles plot creation separately from image success.

```python
from resinsight_mcp.contracts.errors import Failure, OperationResult
from resinsight_mcp.contracts.jobs import Job, Result, ResultImportRequest
from resinsight_mcp.contracts.sessions import ApplicationContext
from resinsight_mcp.results import CurveQuery, ResultRef, ResultsService, SummaryPlotRequest


def require[T](response: OperationResult[T]) -> T:
    if isinstance(response.outcome, Failure):
        raise RuntimeError(response.outcome.error.message)
    return response.outcome.value


def inspect_producer(
    service: ResultsService,
    result: Result,
    job: Job,
    context: ApplicationContext,
    well_name: str,
) -> None:
    loaded = require(service.load(ResultImportRequest(context=context, job=job, result=result)))
    query = CurveQuery(
        result=ResultRef(session_id=result.model.session_id, result_id=result.result_id),
        scope="well",
        keyword="WBHP",
        well_name=well_name,
    )
    curve = require(service.curve(query))
    print(curve.unit, curve.reports, curve.values)
    response = service.show_curve(
        SummaryPlotRequest(context=loaded.case.context, query=query, width=1200, height=800)
    )
    if isinstance(response.outcome, Failure):
        print("Plot creation failed:", response.outcome.error)
        return
    edited = response.outcome.value
    print("Applied plot:", edited.edit.plot_address, edited.edit.context)
    if isinstance(edited.observation.outcome, Failure):
        print("The plot exists, but its image failed:", edited.observation.outcome.error)
    else:
        print("Fresh image:", edited.observation.outcome.value.image.artifact)
    rebound = require(service.rebind(edited.edit.context, (result.result_id,)))
    print("Current case:", rebound[0].case)
```

## Current references and saved projects

A project generation identifies one observed native project state.
Loading another result, creating a summary plot, or reopening a project invalidates earlier object references.
Use the context returned by the successful mutation or inspect the current project through the session service.
Call `rebind(context, result_ids)` to verify loaded cases and obtain fresh bindings for their exact results.
After loading a scenario, rebind both baseline and scenario before further view operations.

A project checkpoint can retain baseline and scenario result identifiers from one session.
After opening its saved native project, call `restore(context, checkpoint_id)` to verify those cases and issue fresh bindings.
Each result keeps its own exact model revision and job identity.
Saved object identifiers alone do not authorize new bindings.

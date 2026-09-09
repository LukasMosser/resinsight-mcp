# OPM Flow service

`OpmFlowService` submits the supported FIELD model profile through the durable job controller.
FIELD uses feet, pounds per square inch, and stock tank barrels.
The service preserves one immutable model revision for each run.
It copies prepared inputs into a unique run directory before submission.
The container receives read-only inputs and a separate writable output directory.

The supported runtime uses Flow 2026.04 in the pinned `openporousmedia/opmreleases` image on `linux/arm64`.
The [Docker job guide](docker-jobs.md) describes process ownership, resource enforcement, cancellation, deadlines, and reconciliation.
The service allows at most two CPUs, 2048 MiB, and 60 wall seconds.
It does not pull images.
The default Docker executable comes from the approved Docker Desktop installation.
An explicit configuration can select another absolute Docker executable.
`FlowConfiguration.check_dependencies()` checks the Docker versions and the local image before a launcher opens workspace storage.
It requires the pinned repository digest and platform through a bounded image inspection.
Missing, unavailable, or mismatched runtimes produce explicit configuration failures.

## Submission and collection

`submit`, `poll`, and `request_cancel` use the durable job controller.
The saved submission records the image digest, platform, Docker versions, resource limits, mounts, command, and expected Flow version.
Collection checks the observed Flow banner against that expected version.
The saved assessment distinguishes the expected version from the observed version.
A successful process exit establishes execution success only.

`collect` requires a confirmed successful job.
The isolated OPM reader requires EGRID, INIT, UNRST, SMSPEC, and UNSMRY outputs.
These formats contain grid geometry, initial properties, restart properties, summary definitions, and summary values.
The service publishes all five outputs, a numerical dataset, and assessment evidence as immutable workspace artifacts.
It then reads all published outputs again before saving the result.
A partial publication retry cannot combine old artifacts with a different numerical dataset.

Collection preserves the reserved result and grid identifiers across retries and service restarts.
A publication failure reports an uncertain mutation effect and leaves no successful result record.
An unchanged retry can finish publication through the reserved artifact identities.
The saved result uses `NumericalAssessment.ACCEPTED` under the explicit `opm-field-validity-v1` policy.
This policy requires trusted successful execution, complete scheduled outputs, verified identity and units, and finite numerical values.
It also requires positive absolute pressures and physically valid water, gas, and remaining oil saturations.
The shared result default remains unassessed for other producers.
Independent numerical reference agreement remains separately unassessed in the evidence.
This acceptance policy does not claim agreement with another simulator or a numerical reference.

## Numerical and identity checks

Collection freshly materializes the immutable input revision before reading output files.
It checks dimensions, active-cell order, cell dimensions, depths, porosity, permeability, and pore volumes against the input inspection.
Pore volume conversion uses exactly 96/539 reservoir barrels per cubic foot.
It checks FIELD units, restart step numbers, elapsed days, calendar dates, summary units, and well identities.
Every scheduled report must appear, including the initial restart report.
The public report series excludes that initial report.

The dataset contains pressure, water saturation, gas saturation, field oil rate, and well bottom-hole pressure.
It preserves the output values without clipping small saturation roundoff.
The water, gas, and combined saturation bounds allow two float32 increments at one, equal to `2.384185791015625e-7`.
Input comparisons allow two representable output increments at the largest reference magnitude, with zero relative tolerance.
This tolerance follows the precision of the output array being checked.
It does not establish an independent simulator accuracy threshold.

The dataset preserves eight corners for every active cell in OPM order.
Its coordinate frame comes from the submitted model revision.
The OPM input bindings do not expose source corner arrays.
Initial collection therefore checks the source properties and geometry measures listed above, then preserves the complete output corner geometry.
It does not claim an independent comparison between input corners and output corners.
The assessment also preserves every INIT array and every report-only summary array through supported OPM readers.

## Exact output verification

`verify_outputs(result, directory)` verifies a materialized result bundle.
It reloads the canonical result, job, run metadata, and immutable inputs.
The directory must contain the five original output basenames.
The method reads those files and compares their dataset and assessment with the immutable collected references.
Changed active-cell geometry, static properties, supported restart values, or summary values cause an explicit failure.
The returned dataset retains the saved model, job, result grid, and report identities.

The verifier shares the same isolated reader with collection.
It uses parsed numerical values and metadata, without byte comparisons.
The result adapter uses this boundary before interpreting materialized files through ResInsight.
Native corner-order conversion belongs to the result adapter.

## Maintained evidence

The maintained tests use the preserved P07 Flow outputs recorded by P08.
The fixture record at `tests/simulators/opm/data/reference/README.md` records source, license, versions, and runtime limits.
The default test suite does not start Docker or a simulator.
It compares pressure and summary values with the existing P08 numerical evidence.
It also exercises missing reports, wrong units, changed wells, invalid saturation, changed geometry, altered static data, and partial publication.

The OPM header definitions establish FIELD unit identity, report step numbers, and calendar date positions.
The [INTEHEAD definitions](https://github.com/OPM/opm-common/blob/release/2025.10/final/opm/output/eclipse/VectorItems/intehead.hpp) define these fields.
The [DOUBHEAD implementation](https://github.com/OPM/opm-common/blob/release/2025.10/final/opm/output/eclipse/DoubHEAD.cpp) defines elapsed simulation days.
These source references support field interpretation, not runtime acceptance.

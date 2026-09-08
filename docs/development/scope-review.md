# Scope review

The supplied scope supports a local service over rips with OPM as the first simulator.
It is a source assessment, not a tested implementation.
This review records upstream evidence inspected on September 8, 2026.

## ResInsight controls

The documented rips API covers launch, project access, case loading, views, snapshots, wells, and property transfer.
These controls support a service without routine mouse automation.
They do not establish a complete engineering model or a Julia result importer.
See the [rips API](https://api.resinsight.org/en/main/rips.html).

The proposed service must distinguish a client connection, engineering workspace, ResInsight instance, and simulator job.
Every mutation needs an explicit session identifier.
An attached application remains owned by the user.

Opening another project invalidates the service's old object identifiers.
A busy application does not necessarily indicate a failed process.
The session implementation needs real tests for both conditions.

## macOS gate

The owner selected macOS for the first demonstration.
The official Mac build instructions set `RESINSIGHT_ENABLE_GRPC=false` and also disable HDF5.
Those instructions do not establish working rips control on macOS.
See the [Mac build guide](https://resinsight.org/releases/build-from-source/build-instructions-mac/).

P01 must prove a build with gRPC and a matching rips package.
It must also prove the chosen OPM execution environment.
If either proof fails, request an owner decision before dependent integration work.

## Native OPM Jobs

ResInsight documents native OPM Flow Jobs for preparing runs and loading results.
Creating a job from a grid case requires the associated DATA input file.
The existing workflow provides a reference for the adapter design.
See [job creation](https://resinsight.org/opm-flow-integration/createnewjob/index.html) and [job properties](https://resinsight.org/opm-flow-integration/jobproperties/index.html).

The inspected source connects the run action to `RicRunJobFeature::runJob`.
This review finds no documented Python interface for the complete job life cycle.
That finding does not prove that no usable interface exists.
See the [job source](https://github.com/OPM/ResInsight/blob/dev/ApplicationLibCode/ProjectDataModel/Jobs/RimOpmFlowJob.cpp) and [API index](https://api.resinsight.org/en/main/genindex.html).

The proposed dedicated OPM adapter keeps job control separate from the viewer.
P01 must record the native Jobs capabilities before this choice becomes final.
Do not add an automatic switch between native Jobs and an external runner.

## Models and wells

A grid defines geometry, not a complete simulation.
Simulation inputs also need rock and fluid properties, initial conditions, well connections, controls, and reporting times.
The plan therefore separates imported decks from constrained generated models.

A visible well does not prove that simulator connections match it.
P09 must prove depth direction, intervals, active cells, names, and controls through completion export.
Unsupported features must produce clear errors.

## Julia results

PyJutulDarcy runs DATA files and returns field values, well values, active-cell states, and elapsed days.
Its Python interface exposes a subset of Julia functionality.
These values need an explicit transfer contract before ResInsight can display them correctly.
See [PyJutulDarcy](https://github.com/sintefmath/PyJutulDarcy).

The JutulDarcy FAQ states that commercial simulator binary outputs are unsupported.
It describes Julia structures and JLD2 storage instead.
The plan therefore requires explicit transfer of cell properties and curves.
See the [JutulDarcy FAQ](https://sintefmath.github.io/JutulDarcy.jl/stable/extras/faq).

The same FAQ gives positive rates for injection and negative rates for production.
P14 must preserve cell order, units, rate signs, report times, and well identities.
Two simulators accepting one deck does not establish equal supported physics or results.

## Native images

MCP tool results support native image blocks beside text blocks.
An image block contains `type: "image"`, image data, and `mimeType`.
A filename in text does not satisfy that contract.
See the [MCP schema](https://modelcontextprotocol.io/specification/2025-11-25/schema).

The actual client must pass the image to the model.
The acceptance experiment uses visible information that text metadata does not reveal.
It must distinguish an image shown in the interface from an image received by the model.

Use supported image decoding and observation metadata to establish usable output.
Do not add byte-level checks or exact pixel comparisons from the original scope.
A failed export must never return an earlier successful image as the new observation.

## Versions and licensing

The inspected rips pages display different documentation versions.
This review does not establish the attachment's claimed latest ResInsight release.
P01 must record an application and rips pair that actually works.

ResInsight and rips use GPL-3.0-or-later.
In particular, rips declares that license in its Python project metadata.
That dependency makes GPL-3.0-or-later a direct project license option.
See [rips metadata](https://github.com/OPM/ResInsight/blob/dev/GrpcInterface/Python/pyproject.toml) and the [rips license](https://github.com/OPM/ResInsight/blob/dev/GrpcInterface/Python/LICENSE).

OPM, Julia packages, example datasets, and copied code each need their own license record.
Process separation does not automatically settle distribution duties.
Review the complete component inventory before distributing combined software.
See the [GNU guidance](https://www.gnu.org/licenses/gpl-faq.en.html#GPLPlugins).

## Reuse and project practice

Evaluate existing projects before copying their implementation.
The OPM MCP project offers related job and result work, while jutul-agent offers Julia worker patterns.
Neither establishes the required persistent ResInsight integration.
See [opm-mcp](https://github.com/ojaogezi/opm-mcp) and [jutul-agent](https://github.com/SINTEF-agentlab/jutul-agent).

The foundation adopts small reviewed changes, contributor setup instructions, and explicit release steps from maintained projects.
It uses focused tests and short commit subjects with explanatory bodies.
It does not copy those projects' entire policies or licenses without a project-specific choice.
See [LLVM policy](https://llvm.org/docs/DeveloperPolicy.html), [uv contributions](https://github.com/astral-sh/uv/blob/main/CONTRIBUTING.md), and [Ruff contributions](https://github.com/astral-sh/ruff/blob/main/CONTRIBUTING.md).

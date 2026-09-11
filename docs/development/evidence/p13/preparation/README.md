# Public workflow preparation

The lead reviewed the complete P13 driver after an independent review found camera, curve, cleanup, and early-discovery gaps.
The [source review](source-review.json) records the corrected behavior and the public domain boundary.
The [shared log](shared-check.log) records 673 passing maintained tests, Ruff, ty, and strict documentation checks.
Fifteen focused driver cases exercise numerical and evidence failures without native or simulator work.

The [environment record](environment.json) identifies the tested source, tool versions, installed interpreter, and documentation changes present during the check.
The driver source was committed before that command.
The [help output](driver-help.log) ran through the clean installed interpreter without starting a native application.

The [exact trial command](trial-command.json) uses the reviewed application wheel at source `38e5aa8d9eca0c81e72ffdbdddfcf561e8735cbe`.
It starts the supplied launcher and performs every domain step through public MCP tools.
The [driver guide](../../../opm-acceptance.md) describes the complete sequence, source identities, numerical checks, images, and cleanup.

At this preparation stage, no P13 native or simulator trial had run.
Native runtime approval and image review were pending.
These historical preparation records do not close P13.
The [current driver guide](../../../opm-acceptance.md) records the later local trial status and remaining publication gate.

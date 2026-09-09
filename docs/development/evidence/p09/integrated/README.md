# P09 integration review

The lead integrated P09 after the launcher, constrained models, model materialization, and session mutation prerequisites merged.
The [environment record](environment.json) identifies the source, working guide changes, versions, and command.
The [shared check](shared-check.log) passed 514 tests, Ruff, formatting, ty, and the strict documentation build.
These checks use controlled application processes and the OPM library.
They do not launch ResInsight or a simulator.

## Test collection repair

The [first combined check](initial-collection.log) found duplicate `wells.test_service` modules.
A [second check](module-rename-collection.log) showed that distinct filenames still shared the same regular Python package name.
The model schedule test now uses `test_schedule_service.py`.
The native test package now uses `tests/resinsight/modeled_wells/`.
These test-only changes preserve helper imports and leave shared pytest configuration unchanged.
The combined shared check passed after both repairs.

## Independent service review

The [focused native service log](independent-native-service-tests.log) records 19 passing public tests on the reviewed native implementation.
The [independent probe](independent-native-service-probe.json) identifies that source commit and distinguishes failures before and after native edits.
A rejected pre-edit case remains ready with `STALE_OBJECT` and `NOT_APPLIED`.
A rejected post-edit depth observation retires the connection with `UNKNOWN`.
The controlled checks do not establish real application behavior.

The review assessed duplicate behavior, control flow, names, ownership, coupling, maintenance cost, public behavior, and important failures.
Native operations use the existing session connection and mutation boundary.
Input publication uses the existing import validation and revision boundary.
The schedule review also checked parsed input preservation and native consistency tolerances.
The combined guide review found no API or lifecycle mismatch and clarified support for multiple perforation intervals.

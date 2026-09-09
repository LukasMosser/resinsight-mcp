# Shared well control contracts

This P02 follow-up supplies shared records for P08 and P09 authored model changes.
These records do not change simulator physics or accepted imported names.
The import parser remains responsible for imported controls.

`WellName` accepts one through eight ASCII characters.
The first character must be a letter.
Later characters can be letters, digits, or underscores.
The authored name rule is stricter than the current import parser.

`FieldSurfaceRate` describes volume per day at surface conditions.
`stb/day` means stock tank barrels per day.
`Mscf/day` means thousand standard cubic feet per day.
Values must be finite and nonnegative.
These labels use FIELD units without conversion.

`ProducerControl` supports `ORAT` and `BHP` modes.
`ORAT` means oil rate control and requires `oil_rate` in `stb/day`.
`InjectorControl` supports `RATE` and `BHP` modes for `WATER` or `GAS`.
`RATE` requires `surface_rate` in `stb/day` for water or `Mscf/day` for gas.
`OPEN` rate controls require positive rates, while `SHUT` rate controls also accept zero.
Both statuses require an explicit rate in rate modes, matching the import parser.

`BHP` means bottom hole pressure control and forbids a rate.
Every control requires finite, positive `bhp_psia`, including shut controls.
`psia` means pounds per square inch absolute.
The rate fields default to `None` for pressure control.
`WellControl` selects its record through the `kind` field, whose values are `producer` and `injector`.
Each concrete record supplies its own `kind` default.

Records reject unknown fields, implicit value conversion, and mutation through the shared `Record` configuration.
JSON input accepts enum strings, while strict Python input requires `WellStatus` members.
The maintained contract tests cover serialization, invalid numbers, name limits, and incompatible control choices.
They do not launch ResInsight or a simulator.

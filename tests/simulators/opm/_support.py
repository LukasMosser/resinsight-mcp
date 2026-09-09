"""Rewrite semantic arrays through the supported OPM writer."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

from opm.io.ecl import EclFile, EclOutput, eclArrType


def rewrite(path: Path, change: Callable[[str, Any], Any]) -> None:
    source = EclFile(str(path))
    arrays = [
        (name, kind, None if kind == eclArrType.MESS else source[index])
        for index, (name, kind, _) in enumerate(source.arrays)
    ]
    target = path.with_suffix(".new")
    output = EclOutput(str(target))
    for name, kind, values in arrays:
        if kind == eclArrType.MESS:
            output.write_message(name)
            continue
        replacement = change(name, values)
        if replacement is None:
            break
        output.write(name, replacement)
    del output
    target.replace(path)

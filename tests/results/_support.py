"""A semantic fixture exposes verifier failures through the public service."""

import json
from pathlib import Path

from resinsight_mcp.contracts.errors import ErrorCode
from resinsight_mcp.contracts.jobs import Result
from resinsight_mcp.contracts.results import ResultDataset
from resinsight_mcp.results._common import fail, operation


class FixtureVerifier:
    def __init__(self, store):
        self.store = store
        self.replacement: ResultDataset | None = None

    @operation
    def verify_outputs(self, result: Result, directory: Path) -> ResultDataset:
        assert result.manifest is not None
        for output in result.manifest.outputs:
            document = json.loads((directory / f"CASE.{output.role.value}").read_text())
            if (
                document["role"] != output.role.value
                or document["unit_system"] != "FIELD"
                or document["values"] != [1, 2]
            ):
                fail(ErrorCode.INVALID_MODEL, "The fixture output content changed.")
        if self.replacement is not None:
            return self.replacement
        with self.store.open_artifact(result.manifest.numerical_data) as stream:
            return ResultDataset.model_validate_json(stream.read())

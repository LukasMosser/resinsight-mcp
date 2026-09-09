"""Native readback rejects wrong values, mappings, times, and file identities."""

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast

import pytest

from resinsight_mcp.contracts.errors import ContractError
from resinsight_mcp.resinsight.sessions._backend import ApplicationAccess
from resinsight_mcp.results import rips as native
from resinsight_mcp.results._bundles import ResultBundle


class Case:
    def __init__(self, bundle):
        self.file_path = str(bundle.egrid)
        self.cells = [
            SimpleNamespace(grid_index=0, local_ijk=SimpleNamespace(i=i, j=0, k=0)) for i in (0, 1)
        ]
        self.days = [0, 1]
        self.pressure = [100, 200]
        # ResInsight uses clockwise face corners, unlike OPM's I-fastest order.
        self.corners = [
            SimpleNamespace(
                **{
                    f"c{index}": SimpleNamespace(x=i + x, y=y, z=100 + z)
                    for index, (x, y, z) in enumerate(
                        (
                            (0, 0, 0),
                            (1, 0, 0),
                            (1, 1, 0),
                            (0, 1, 0),
                            (0, 0, 1),
                            (1, 0, 1),
                            (1, 1, 1),
                            (0, 1, 1),
                        )
                    )
                }
            )
            for i in (0, 1)
        ]

    def address(self):
        return 10

    def grid(self):
        return SimpleNamespace(dimensions=lambda: SimpleNamespace(i=2, j=1, k=1))

    def cell_info_for_active_cells(self):
        return self.cells

    def active_cell_corners(self):
        return self.corners

    def days_since_start(self):
        return self.days

    def time_steps(self):
        return [SimpleNamespace(year=2015, month=1, day=day) for day in (1, 2)]

    def active_cell_property(self, category, name, index):
        assert category == "DYNAMIC_NATIVE" and index == 1
        return self.pressure if name == "PRESSURE" else [0.2, 0.3]


class Summary:
    def __init__(self, bundle):
        self.summary_header_filename = str(bundle.smspec)
        self.dates = [int(datetime(2015, 1, day, tzinfo=UTC).timestamp()) for day in (1, 2)]
        self.values = [90, 95]

    def available_time_steps(self):
        return SimpleNamespace(values=self.dates)

    def summary_vector_values(self, address):
        assert address == "WBHP:PROD"
        return SimpleNamespace(values=self.values)


def setup(monkeypatch, publish, tmp_path):
    result, _, dataset = publish()
    bundle = ResultBundle(result, tmp_path, tmp_path / "CASE.EGRID", tmp_path / "CASE.SMSPEC")
    case, summary = Case(bundle), Summary(bundle)
    project = SimpleNamespace(cases=lambda: [case], summary_cases=lambda: [summary])
    application = SimpleNamespace(call=lambda callback: callback())
    monkeypatch.setattr(native, "_client", lambda access: (application, project))
    return native.RipsResultBackend(), cast(ApplicationAccess, None), bundle, dataset, case, summary


def test_readback_matches_semantic_reference_with_extra_initial_report(
    monkeypatch, publish, tmp_path
):
    backend, access, bundle, dataset, _, _ = setup(monkeypatch, publish, tmp_path)
    backend.verify(access, "10", bundle, dataset)


@pytest.mark.parametrize(
    "difference", ["mapping", "time", "pressure", "curve", "dates", "path", "geometry"]
)
def test_readback_rejects_semantic_mismatches(monkeypatch, publish, tmp_path, difference):
    backend, access, bundle, dataset, case, summary = setup(monkeypatch, publish, tmp_path)
    if difference == "mapping":
        case.cells.reverse()
    elif difference == "time":
        case.days[1] = 2
    elif difference == "pressure":
        case.pressure[0] = 110
    elif difference == "curve":
        summary.values[1] = 96
    elif difference == "dates":
        summary.dates[0] = summary.dates[1]
    elif difference == "geometry":
        case.corners[0].c0.z += 0.01
    else:
        case.file_path = str(tmp_path / "OTHER.EGRID")
    with pytest.raises(ContractError):
        backend.verify(access, "10", bundle, dataset)

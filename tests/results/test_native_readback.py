"""Native readback rejects wrong values, mappings, times, and file identities."""

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast

import pytest

from resinsight_mcp.contracts.errors import ContractError, ErrorCode
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
        self.name = "Original result"
        self.name_setting = "AUTO"
        self.saved_name = self.name
        self.views = 0
        self.native_address = 10
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
        return self.native_address

    def update(self):
        self.saved_name = self.name

    def create_view(self):
        self.views += 1

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


class LoadingProject:
    def __init__(self, bundle, auto_summary):
        self.bundle = bundle
        self.auto_summary = auto_summary
        self.case_rows = []
        self.summary_rows = []

    def cases(self):
        return self.case_rows

    def summary_cases(self):
        return self.summary_rows

    def import_summary_case(self, *, file_name):
        if any(item.summary_header_filename == file_name for item in self.summary_rows):
            raise RuntimeError("No result returned from Method")
        summary = Summary(self.bundle)
        assert summary.summary_header_filename == file_name
        self.summary_rows.append(summary)
        return summary

    def load_case(self, path):
        assert path == str(self.bundle.egrid)
        case = Case(self.bundle)
        self.case_rows.append(case)
        if self.auto_summary:
            self.summary_rows = [
                item
                for item in self.summary_rows
                if item.summary_header_filename != str(self.bundle.smspec)
            ]
            self.summary_rows.append(Summary(self.bundle))
        return case


def loading_setup(monkeypatch, publish, tmp_path, auto_summary):
    result, _, dataset = publish()
    bundle = ResultBundle(result, tmp_path, tmp_path / "CASE.EGRID", tmp_path / "CASE.SMSPEC")
    project = LoadingProject(bundle, auto_summary)
    application = SimpleNamespace(call=lambda callback, **kwargs: callback())
    monkeypatch.setattr(native, "_client", lambda access: (application, project))
    return native.RipsResultBackend(), cast(ApplicationAccess, None), bundle, dataset, project


@pytest.mark.parametrize("auto_summary", [False, True])
def test_load_and_verify_with_native_summary_import_preferences(
    monkeypatch, publish, tmp_path, auto_summary
):
    backend, access, bundle, dataset, project = loading_setup(
        monkeypatch, publish, tmp_path, auto_summary
    )
    other = ResultBundle(
        bundle.result, tmp_path, tmp_path / "OTHER.EGRID", tmp_path / "OTHER.SMSPEC"
    )
    other_case, other_summary = Case(other), Summary(other)
    other_case.native_address = 20
    project.case_rows.append(other_case)
    project.summary_rows.append(other_summary)
    address = backend.load(access, bundle, dataset)
    backend.verify(access, address, bundle, dataset)
    loaded = project.case_rows[1]
    assert loaded.file_path == str(bundle.egrid)
    assert loaded.saved_name == f"{bundle.result.result_id} ({bundle.result.model.revision_id})"
    assert loaded.name_setting == "CUSTOM_NAME" and loaded.views == 1
    assert len(project.summary_rows) == 2
    assert project.case_rows[0] is other_case and project.summary_rows[0] is other_summary
    assert other_case.saved_name == "Original result" and other_case.views == 0
    assert other_case.pressure == [100, 200] and other_summary.values == [90, 95]


@pytest.mark.parametrize("existing", ["grid", "summary"])
def test_load_rejects_existing_result_paths_without_changing_them(
    monkeypatch, publish, tmp_path, existing
):
    backend, access, bundle, dataset, project = loading_setup(monkeypatch, publish, tmp_path, True)
    case, summary = Case(bundle), Summary(bundle)
    if existing == "grid":
        project.case_rows.append(case)
    else:
        project.summary_rows.append(summary)
    before_cases, before_summaries = list(project.case_rows), list(project.summary_rows)
    with pytest.raises(ContractError) as raised:
        backend.load(access, bundle, dataset)
    assert raised.value.error.code == ErrorCode.CONFLICT
    assert project.case_rows == before_cases and project.summary_rows == before_summaries
    assert case.saved_name == "Original result" and case.views == 0
    assert case.pressure == [100, 200] and summary.values == [90, 95]


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

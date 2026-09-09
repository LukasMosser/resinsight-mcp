"""Summary export targets one native window and retains numerical verification."""

from types import SimpleNamespace

import pytest

from resinsight_mcp.contracts.errors import ContractError, ErrorCode, MutationEffect
from resinsight_mcp.results import CurveValues
from resinsight_mcp.results import rips as native

from .test_native_readback import setup


class Window:
    def __init__(self, identifier):
        self.id = identifier
        self.exports = []
        self.number_of_columns = native.rips.NumberOfColumns._2
        self.rows_per_page = native.rips.RowsPerPage._2
        self.applied_layout = (self.number_of_columns, self.rows_per_page)

    def update(self):
        self.applied_layout = (self.number_of_columns, self.rows_per_page)

    def export_snapshot(self, *, export_folder, width, height):
        self.exports.append((export_folder, width, height, self.applied_layout))


class Plot:
    def __init__(self, windows, summary):
        self.windows = windows
        self.parent = windows[1]
        self.summary = summary
        self.change_values = False

    def address(self):
        return 77

    def update(self):
        if self.change_values:
            self.summary.values[1] += 1

    def ancestor(self, cls):
        assert cls is native.rips.MultiPlot
        return self.parent

    def export_snapshot(self, *, export_folder, width, height):
        # A child plot's native id is -1, which selects every docked plot.
        for window in self.windows:
            window.export_snapshot(export_folder=export_folder, width=width, height=height)


def plotting_setup(monkeypatch, publish, tmp_path):
    backend, access, bundle, dataset, _, summary = setup(monkeypatch, publish, tmp_path)
    windows = [Window(3), Window(4)]
    plot = Plot(windows, summary)

    def new_plot(*, summary_cases, address):
        assert summary_cases == [summary] and address == "WBHP:PROD"
        return plot

    project = SimpleNamespace(
        summary_cases=lambda: [summary],
        descendants=lambda cls: [SimpleNamespace(new_summary_plot=new_plot)],
    )
    application = SimpleNamespace(call=lambda callback, **kwargs: callback())
    monkeypatch.setattr(native, "_client", lambda access: (application, project))
    curve = CurveValues(
        result=bundle.result,
        reports=dataset.report_series.reports,
        **dataset.curves[0].model_dump(),
    )
    return backend, access, bundle, dataset, curve, windows, plot


def test_summary_export_targets_its_parent_among_multiple_windows(monkeypatch, publish, tmp_path):
    backend, access, bundle, dataset, curve, windows, plot = plotting_setup(
        monkeypatch, publish, tmp_path
    )
    address = backend.show_curve(access, bundle, dataset, curve, tmp_path, 1200, 800)
    assert address == "77"
    assert windows[0].exports == []
    assert windows[1].exports == [(str(tmp_path), 1200, 800, ("1", "1"))]
    assert windows[0].applied_layout == ("2", "2")
    assert (windows[0].number_of_columns, windows[0].rows_per_page) == ("2", "2")
    assert plot.normalize_curve_y_values is False and plot.is_using_auto_name is False
    assert plot.plot_description == f"{curve.result.result_id} WBHP:PROD ({curve.unit.value})"


@pytest.mark.parametrize("failure", ["missing_parent", "all_windows_id", "changed_values"])
def test_summary_export_rejects_missing_target_or_changed_values(
    monkeypatch, publish, tmp_path, failure
):
    backend, access, bundle, dataset, curve, windows, plot = plotting_setup(
        monkeypatch, publish, tmp_path
    )
    if failure == "missing_parent":
        plot.parent = None
    elif failure == "all_windows_id":
        windows[1].id = -1
    else:
        plot.change_values = True
    with pytest.raises(ContractError) as raised:
        backend.show_curve(access, bundle, dataset, curve, tmp_path, 1200, 800)
    expected = ErrorCode.INVALID_MODEL if failure == "changed_values" else ErrorCode.RENDER_FAILED
    assert raised.value.error.code == expected
    assert raised.value.error.effect == MutationEffect.UNKNOWN
    assert all(window.exports == [] for window in windows)
    assert all(window.applied_layout == ("2", "2") for window in windows)

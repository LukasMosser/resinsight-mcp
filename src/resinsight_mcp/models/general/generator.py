"""Generate original folded and faulted corner-point layers with rock fields."""

import numpy as np

from .arrays import NumericArray, fail
from .records import GeologicalRequest


def generate(request: GeologicalRequest) -> dict[str, NumericArray]:
    nx, ny, nz = request.shape.nx, request.shape.ny, request.shape.nz
    x = np.linspace(0, request.extent_x, nx + 1)
    y = np.linspace(0, request.extent_y, ny + 1)
    px, py = np.meshgrid(x, y)
    cx, cy = np.meshgrid((x[:-1] + x[1:]) / 2, (y[:-1] + y[1:]) / 2)
    xx, yy = np.meshgrid(
        np.stack((x[:-1], x[1:]), axis=1).ravel(), np.stack((y[:-1], y[1:]), axis=1).ravel()
    )
    surface = np.full_like(xx, request.top_depth)
    for fold in request.folds:
        surface += (
            fold.amplitude
            * np.sin(2 * np.pi * xx / fold.wavelength_x + fold.phase)
            * np.cos(2 * np.pi * yy / fold.wavelength_y)
        )
    offset = np.zeros_like(cx)
    for fault in request.faults:
        offset += (cx > fault.intercept + fault.slope * cy) * fault.throw
    surface += offset.repeat(2, axis=0).repeat(2, axis=1)
    thickness = request.thickness * (
        1
        + request.thickness_variation
        * np.cos(2 * np.pi * xx / request.extent_x)
        * np.cos(2 * np.pi * yy / request.extent_y)
    )
    levels = np.arange(nz + 1, dtype=np.float64) / nz
    levels = np.stack((levels[:-1], levels[1:]), axis=1).ravel()
    zcorn = surface[None, :, :] + levels[:, None, None] * thickness[None, :, :]
    coord = np.empty((ny + 1, nx + 1, 2, 3), dtype=np.float64)
    coord[:, :, :, 0] = px[:, :, None]
    coord[:, :, :, 1] = py[:, :, None]
    coord[:, :, 0, 2] = zcorn.min() - request.thickness
    coord[:, :, 1, 2] = zcorn.max() + request.thickness
    active = np.ones((nz, ny, nx), dtype=np.int64)
    if request.active_ellipse:
        active[:] = (
            ((cx / request.extent_x - 0.5) / 0.5) ** 2 + ((cy / request.extent_y - 0.5) / 0.5) ** 2
        ) < 1
    fractions = (np.arange(nz) + 0.5) / nz
    band_index = np.searchsorted([b.bottom_fraction for b in request.bands], fractions)
    porosity = np.broadcast_to(
        np.array([b.porosity for b in request.bands])[band_index, None, None], (nz, ny, nx)
    ).copy()
    perm = np.broadcast_to(
        np.array([b.permeability_md for b in request.bands])[band_index, None, None], (nz, ny, nx)
    ).copy()
    if request.channel:
        channel = request.channel
        center = channel.center_y + channel.amplitude * np.sin(2 * np.pi * cx / channel.wavelength)
        weight = np.exp(-0.5 * ((cy - center) / channel.width) ** 2)
        perm *= 1 + (channel.permeability_multiplier - 1) * weight
        porosity += channel.porosity_increment * weight
    if np.any(porosity <= 0) or np.any(porosity >= 1):
        fail("The channel and rock bands produce porosity outside zero and one.")
    return {
        "COORD": coord.ravel(),
        "ZCORN": zcorn.ravel(),
        "ACTNUM": active.ravel(),
        "PORO": porosity.ravel(),
        "PERMX": perm.ravel(),
        "PERMY": perm.ravel(),
        "PERMZ": perm.ravel(),
    }

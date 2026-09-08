"""Convert camera geometry to the native row-major view matrix."""

from collections.abc import Sequence
from math import isclose, sqrt

from resinsight_mcp.contracts.observations import Camera, Projection, Vector3


def _dot(a: Sequence[float], b: Sequence[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def _unit(a: Sequence[float]) -> Vector3:
    length = sqrt(_dot(a, a))
    if length == 0:
        raise ValueError("A camera axis has zero length.")
    return (a[0] / length, a[1] / length, a[2] / length)


def _cross(a: Sequence[float], b: Sequence[float]) -> Vector3:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def view_matrix(camera: Camera) -> list[float]:
    """Use OpenGL look-at axes and CAF row-major text serialization."""
    backward = _unit(tuple(p - t for p, t in zip(camera.position, camera.target, strict=True)))
    right = _unit(_cross(camera.up, backward))
    up = _cross(backward, right)
    return [
        value for axis in (right, up, backward) for value in (*axis, -_dot(axis, camera.position))
    ] + [0.0, 0.0, 0.0, 1.0]


def read_camera(
    matrix: Sequence[float],
    target: Sequence[float],
    perspective: bool,
    field_of_view: float,
    height: float,
) -> Camera:
    if len(matrix) != 16 or len(target) != 3:
        raise ValueError("The native camera geometry has invalid dimensions.")
    axes = (matrix[0:3], matrix[4:7], matrix[8:11])
    for i, axis in enumerate(axes):
        for j, other in enumerate(axes):
            if not isclose(_dot(axis, other), float(i == j), abs_tol=1e-8):
                raise ValueError("The native camera matrix is not rigid.")
    if any(not isclose(a, b, abs_tol=1e-8) for a, b in zip(matrix[12:], (0, 0, 0, 1), strict=True)):
        raise ValueError("The native camera matrix is not affine.")
    position = tuple(-sum(axes[j][i] * matrix[j * 4 + 3] for j in range(3)) for i in range(3))
    backward = _unit(tuple(p - t for p, t in zip(position, target, strict=True)))
    if not all(isclose(a, b, abs_tol=1e-7) for a, b in zip(backward, axes[2], strict=True)):
        raise ValueError("The native camera direction disagrees with its target.")
    if not isclose(_dot(_cross(axes[0], axes[1]), axes[2]), 1.0, abs_tol=1e-8):
        raise ValueError("The native camera axes reverse orientation.")
    return Camera(
        position=(position[0], position[1], position[2]),
        target=(target[0], target[1], target[2]),
        up=(axes[1][0], axes[1][1], axes[1][2]),
        projection=Projection.PERSPECTIVE if perspective else Projection.ORTHOGRAPHIC,
        field_of_view_degrees=field_of_view if perspective else None,
        parallel_scale=None if perspective else height / 2,
    )


def camera_matches(expected: Camera, actual: Camera) -> bool:
    """Compare equivalent orientations after native normalization and text rounding."""
    if expected.projection != actual.projection:
        return False
    values = zip(view_matrix(expected), view_matrix(actual), strict=True)
    if not all(isclose(a, b, rel_tol=1e-8, abs_tol=1e-7) for a, b in values):
        return False
    if not all(
        isclose(a, b, rel_tol=1e-8, abs_tol=1e-7)
        for a, b in zip(expected.target, actual.target, strict=True)
    ):
        return False
    return isclose(
        expected.field_of_view_degrees or expected.parallel_scale or 0,
        actual.field_of_view_degrees or actual.parallel_scale or 0,
        rel_tol=1e-8,
        abs_tol=1e-7,
    )

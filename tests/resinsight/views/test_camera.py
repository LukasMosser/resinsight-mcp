"""Camera geometry preserves the visible pose and projection size."""

import pytest

from resinsight_mcp.contracts.observations import Camera, Projection
from resinsight_mcp.resinsight.views._camera import camera_matches, read_camera, view_matrix


@pytest.mark.parametrize("projection", list(Projection))
def test_camera_preserves_pose_and_projection(projection: Projection) -> None:
    camera = Camera(
        position=(12, -8, 32),
        target=(2, 3, 4),
        up=(0, 0, 2),
        projection=projection,
        field_of_view_degrees=55 if projection == Projection.PERSPECTIVE else None,
        parallel_scale=18 if projection == Projection.ORTHOGRAPHIC else None,
    )
    actual = read_camera(
        view_matrix(camera), camera.target, projection == Projection.PERSPECTIVE, 55, 36
    )
    assert actual.position == pytest.approx(camera.position)
    assert actual.target == camera.target
    assert camera_matches(camera, actual)
    assert actual.parallel_scale == camera.parallel_scale
    assert actual.field_of_view_degrees == camera.field_of_view_degrees


def test_look_at_places_eye_at_origin_and_target_in_front() -> None:
    camera = Camera(
        position=(10, 20, 30),
        target=(10, 20, 20),
        up=(0, 1, 0),
        projection=Projection.PERSPECTIVE,
        field_of_view_degrees=40,
    )
    matrix = view_matrix(camera)

    def transform(point: tuple[float, float, float]) -> list[float]:
        return [
            sum(matrix[4 * row + column] * point[column] for column in range(3))
            + matrix[4 * row + 3]
            for row in range(3)
        ]

    assert transform(camera.position) == pytest.approx((0, 0, 0))
    assert transform(camera.target) == pytest.approx((0, 0, -10))


def test_camera_detects_changed_projection_extent() -> None:
    camera = Camera(
        position=(0, 0, 10),
        target=(0, 0, 0),
        up=(0, 1, 0),
        projection=Projection.ORTHOGRAPHIC,
        parallel_scale=10,
    )
    actual = read_camera(view_matrix(camera), camera.target, False, 40, 30)
    assert not camera_matches(camera, actual)


def test_camera_rejects_scaled_native_matrix() -> None:
    with pytest.raises(ValueError, match="not rigid"):
        read_camera([2, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1], (0, 0, -1), True, 40, 20)


def test_camera_rejects_orientation_that_disagrees_with_target() -> None:
    camera = Camera(
        position=(0, 0, 10),
        target=(0, 0, 0),
        up=(0, 1, 0),
        projection=Projection.PERSPECTIVE,
        field_of_view_degrees=40,
    )
    turned = camera.model_copy(update={"target": (0, 0, 20)})
    with pytest.raises(ValueError, match="direction disagrees"):
        read_camera(view_matrix(turned), camera.target, True, 40, 20)


@pytest.mark.parametrize("projection", list(Projection))
def test_only_orthographic_depth_translation_preserves_projection(projection: Projection) -> None:
    camera = Camera(
        position=(0, 0, 10),
        target=(0, 0, 0),
        up=(0, 1, 0),
        projection=projection,
        parallel_scale=10 if projection == Projection.ORTHOGRAPHIC else None,
        field_of_view_degrees=40 if projection == Projection.PERSPECTIVE else None,
    )
    farther = camera.model_copy(update={"position": (0, 0, 20)})
    assert camera_matches(camera, farther) == (projection == Projection.ORTHOGRAPHIC)
    shifted = camera.model_copy(update={"position": (2, 0, 10), "target": (2, 0, 0)})
    assert not camera_matches(camera, shifted)

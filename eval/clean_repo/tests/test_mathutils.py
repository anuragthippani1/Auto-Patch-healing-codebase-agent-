import pytest

from toolkit.mathutils import clamp, mean, median, percent_change, scale_to_unit


def test_clamp_inside_range():
    assert clamp(5, 0, 10) == 5


def test_clamp_outside_range():
    assert clamp(-3, 0, 10) == 0
    assert clamp(42, 0, 10) == 10


def test_clamp_rejects_inverted_range():
    with pytest.raises(ValueError):
        clamp(1, 10, 0)


def test_scale_to_unit_inside_range():
    assert scale_to_unit(5, 0, 10) == 0.5
    assert scale_to_unit(15, 10, 20) == 0.5


def test_scale_to_unit_at_the_ends():
    assert scale_to_unit(0, 0, 10) == 0.0
    assert scale_to_unit(10, 0, 10) == 1.0


def test_scale_to_unit_clamps_values_outside_range():
    assert scale_to_unit(-4, 0, 10) == 0.0
    assert scale_to_unit(99, 0, 10) == 1.0


def test_scale_to_unit_rejects_empty_range():
    with pytest.raises(ValueError):
        scale_to_unit(1, 3, 3)


def test_mean():
    assert mean([1, 2, 3, 4]) == 2.5
    with pytest.raises(ValueError):
        mean([])


def test_median():
    assert median([3, 1, 2]) == 2
    assert median([4, 1, 3, 2]) == 2.5
    with pytest.raises(ValueError):
        median([])


def test_percent_change():
    assert percent_change(50, 75) == 50.0
    assert percent_change(80, 60) == -25.0
    with pytest.raises(ValueError):
        percent_change(0, 5)

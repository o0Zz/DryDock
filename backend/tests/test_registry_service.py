import pytest

from app.services.registry_service import DOCKER_HUB, find_newer, parse_reference, parse_version


@pytest.mark.parametrize(
    ("image", "expected"),
    [
        ("nginx", (DOCKER_HUB, "library/nginx", "latest")),
        ("nginx:1.25-alpine", (DOCKER_HUB, "library/nginx", "1.25-alpine")),
        ("docker.io/library/nginx:1", (DOCKER_HUB, "library/nginx", "1")),
        (
            "homeassistant/home-assistant:2025.10.4",
            (DOCKER_HUB, "homeassistant/home-assistant", "2025.10.4"),
        ),
        (
            "ghcr.io/home-assistant/home-assistant:stable",
            ("ghcr.io", "home-assistant/home-assistant", "stable"),
        ),
        ("localhost:5000/app:1.0", ("localhost:5000", "app", "1.0")),
        ("registry.local:5000/team/app", ("registry.local:5000", "team/app", "latest")),
        ("nginx:1.25@sha256:abc", (DOCKER_HUB, "library/nginx", "1.25")),
    ],
)
def test_parse_reference(image: str, expected: tuple[str, str, str]) -> None:
    assert parse_reference(image) == expected


@pytest.mark.parametrize("tag", ["latest", "stable", "beta", "dev", "rc"])
def test_floating_tags_are_not_versions(tag: str) -> None:
    assert parse_version(tag) is None
    assert find_newer(tag, ["1.0", "2.0"]) == (None, None)


def test_calendar_versions_skip_prereleases() -> None:
    tags = [
        "2025.10.3", "2025.10.4", "2025.12.4", "2026.9.3", "2026.10.1",
        "2026.11.0b2", "2026.11.0.dev20261015", "stable", "latest", "2026.10",
    ]
    # The year counts as the major, so 2025.12.4 is the newest same-major tag.
    assert find_newer("2025.10.4", tags) == ("2026.10.1", "2025.12.4")


def test_major_and_same_major() -> None:
    tags = ["15.8", "16.2", "16.4", "17.0", "18.1", "18.1-alpine", "16"]
    assert find_newer("16.2", tags) == ("18.1", "16.4")


def test_same_major_omitted_when_equal_to_newest() -> None:
    assert find_newer("1.2.3", ["1.2.3", "1.3.0", "1.4.1"]) == ("1.4.1", None)


def test_suffix_variant_stays_in_its_lane() -> None:
    tags = ["1.25-alpine", "1.27", "1.27-alpine", "1.27-perl"]
    assert find_newer("1.25-alpine", tags) == ("1.27-alpine", None)


def test_v_prefix_and_build_suffix() -> None:
    assert find_newer("v1.2.0", ["v1.2.0", "v1.10.0", "1.11.0"]) == ("v1.10.0", None)
    # linuxserver-style build numbers order after the version
    assert find_newer("1.2.3-ls40", ["1.2.3-ls41", "1.2.3-ls9"]) == ("1.2.3-ls41", None)


def test_outlier_major_is_ignored() -> None:
    tags = ["4.6.0", "4.6.7", "5.0.1", "5.1.2", "20.04.1"]
    assert find_newer("4.6.0", tags) == ("5.1.2", "4.6.7")
    # Even-numbered majors (node 18 -> 20 -> 22) are still reachable.
    assert find_newer("18.1.0", ["20.0.0", "22.3.0"]) == ("22.3.0", None)


def test_nothing_newer() -> None:
    assert find_newer("2.0", ["1.0", "1.9", "2.0"]) == (None, None)

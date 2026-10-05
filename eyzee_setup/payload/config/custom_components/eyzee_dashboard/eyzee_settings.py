import logging
import os

import yaml


_LOGGER = logging.getLogger(__name__)

SETTINGS_YAML = "/config/eyzee/state/settings.yaml"

DEFAULT_AURA_RGB = [180, 80, 255]


def _normalise_rgb(value) -> list[int]:
    """Return a valid RGB colour or the default Aura colour."""

    if (
        not isinstance(value, (list, tuple))
        or len(value) != 3
    ):
        return DEFAULT_AURA_RGB.copy()

    try:
        rgb = [
            max(0, min(255, int(channel)))
            for channel in value
        ]
    except (TypeError, ValueError):
        return DEFAULT_AURA_RGB.copy()

    return rgb


def _read_settings() -> dict:
    """Read and normalise EyZEE Home settings."""

    try:
        with open(
            SETTINGS_YAML,
            "r",
            encoding="utf-8",
        ) as file:
            data = yaml.safe_load(file) or {}

    except FileNotFoundError:
        data = {}

    except Exception as err:
        _LOGGER.warning(
            "EyZEE settings: failed to read %s: %s",
            SETTINGS_YAML,
            err,
        )
        data = {}

    if not isinstance(data, dict):
        data = {}

    data.setdefault("version", 1)

    if not isinstance(data.get("lighting"), dict):
        data["lighting"] = {}

    data["lighting"]["aura_rgb"] = _normalise_rgb(
        data["lighting"].get("aura_rgb")
    )

    return data


def get_aura_rgb() -> list[int]:
    """Return the whole-home Aura RGB colour."""

    settings = _read_settings()

    return settings["lighting"]["aura_rgb"].copy()


def save_aura_rgb(value) -> list[int]:
    """Save and return the whole-home Aura RGB colour."""

    rgb = _normalise_rgb(value)
    settings = _read_settings()

    settings["lighting"]["aura_rgb"] = rgb

    directory = os.path.dirname(SETTINGS_YAML)

    os.makedirs(
        directory,
        exist_ok=True,
    )

    temp_path = f"{SETTINGS_YAML}.tmp"

    with open(
        temp_path,
        "w",
        encoding="utf-8",
    ) as file:
        yaml.safe_dump(
            settings,
            file,
            sort_keys=False,
            allow_unicode=True,
        )

    os.replace(
        temp_path,
        SETTINGS_YAML,
    )

    return rgb.copy()
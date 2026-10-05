"""EyZEE device profile loader."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

_LOGGER = logging.getLogger(__name__)

DEVICE_PROFILES_YAML = Path("/config/eyzee/state/device_profiles.yaml")


def load_device_profiles() -> dict[str, Any]:
    """Load EyZEE device profiles from YAML."""
    if not DEVICE_PROFILES_YAML.exists():
        _LOGGER.warning("Device profiles file not found: %s", DEVICE_PROFILES_YAML)
        return {"version": 1, "profiles": {}}

    try:
        with DEVICE_PROFILES_YAML.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception as err:
        _LOGGER.exception("Failed to load device profiles: %s", err)
        return {"version": 1, "profiles": {}}

    if not isinstance(data, dict):
        _LOGGER.warning("Device profiles YAML is not a dict, using empty profiles.")
        return {"version": 1, "profiles": {}}

    data.setdefault("version", 1)
    data.setdefault("profiles", {})
    return data


def get_profiles() -> dict[str, dict[str, Any]]:
    """Return just the profiles dictionary."""
    data = load_device_profiles()
    profiles = data.get("profiles", {})
    if not isinstance(profiles, dict):
        return {}
    return profiles
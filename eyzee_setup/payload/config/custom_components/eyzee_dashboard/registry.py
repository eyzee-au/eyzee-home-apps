from __future__ import annotations

import os
from typing import Any, Dict

import yaml

REGISTRY_PATH = "/config/eyzee/state/device_registry.yaml"

def _ensure_parent_dir(path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)

def load_registry(path: str = REGISTRY_PATH) -> Dict[str, Any]:
    """Load registry YAML (always returns a dict with version + devices)."""
    if not os.path.exists(path):
        return {"version": 1, "devices": {}}

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    # Normalize minimal shape
    if not isinstance(data, dict):
        data = {}
    data.setdefault("version", 1)
    data.setdefault("devices", {})
    if not isinstance(data["devices"], dict):
        data["devices"] = {}
    return data

def save_registry(registry: Dict[str, Any], path: str = REGISTRY_PATH) -> None:
    """Persist registry YAML safely."""
    _ensure_parent_dir(path)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(registry, f, sort_keys=False, allow_unicode=True)

def upsert_device(
    device_id: str,
    name: str,
    room: str,
    device_type: str,
    z2m_friendly_name: str,
    path: str = REGISTRY_PATH,
) -> Dict[str, Any]:
    """Insert/update a device record and return the full registry."""
    registry = load_registry(path)
    devices = registry.setdefault("devices", {})

    devices[device_id] = {
        "name": name,
        "room": room,
        "type": device_type,
        "z2m_friendly_name": z2m_friendly_name,
        "capabilities": [],  # reserved for later
    }

    save_registry(registry, path)
    return registry
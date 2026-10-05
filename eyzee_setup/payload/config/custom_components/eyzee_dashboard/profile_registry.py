"""Helpers to convert EyZEE profile matches into registry records."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def build_registry_entry_from_profile(
    discovered: dict[str, Any],
    room: str,
    area_label: str,
    device_name: str,
    display_label: str | None = None,
) -> dict[str, Any]:
    """Build a device_registry.yaml entry from an enriched discovered device."""

    eyzee = discovered.get("eyzee", {})
    integration = discovered.get("integration", "unknown")
    manufacturer_name = discovered.get("manufacturer_name")
    model_id = discovered.get("model_id")
    profile_id = discovered.get("profile_id")

    final_display_label = display_label or eyzee.get("product_name") or device_name

    entry: dict[str, Any] = {
        "profile_id": profile_id,
        "room": room,
        "area_label": area_label,
        "device_type": eyzee.get("device_type", "unknown"),
        "type_label": eyzee.get("product_name", "Unknown Device"),
        "device_name": device_name,
        "name_label": device_name.replace("_", " ").title(),
        "display_label": final_display_label,
        "integration": integration,
        "match": {
            "manufacturer_name": manufacturer_name,
            "model_id": model_id,
        },
        "meta": {
            "created": _now_iso(),
            "updated": _now_iso(),
            "notes": "Auto-profiled by EyZEE device profile matcher",
            "tags": ["eyzee", integration],
        },
    }

    if integration == "zha":
        entry["zha"] = {
            "ieee": discovered.get("ieee"),
            "device_id": discovered.get("device_id"),
            "friendly_name": discovered.get("friendly_name"),
            "entities": deepcopy(discovered.get("entities", {})),
        }

    if integration == "z2m":
        entry["z2m"] = {
            "friendly_name": discovered.get("friendly_name"),
            "ieee": discovered.get("ieee"),
            "entities": deepcopy(discovered.get("entities", {})),
        }

    return entry
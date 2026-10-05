"""EyZEE device profile matcher."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .device_profiles import get_profiles


def _safe_lower(value: Any) -> str:
    """Return lowercase stripped string safely."""
    if value is None:
        return ""
    return str(value).strip().lower()


def _matches_fingerprint(
    device: dict[str, Any],
    fingerprint: dict[str, Any],
) -> bool:
    """Check whether a normalized device matches one fingerprint."""

    dev_integration = _safe_lower(device.get("integration"))

    dev_manufacturer = _safe_lower(
        device.get("manufacturer_name")
        or device.get("manufacturer")
    )

    dev_model = _safe_lower(
        device.get("model_id")
        or device.get("model")
    )

    fp_integration = _safe_lower(fingerprint.get("integration"))

    fp_manufacturer = _safe_lower(
        fingerprint.get("manufacturer_name")
        or fingerprint.get("manufacturer")
    )

    fp_model = _safe_lower(
        fingerprint.get("model_id")
        or fingerprint.get("model")
    )

    if fp_integration and dev_integration != fp_integration:
        return False

    if fp_manufacturer and dev_manufacturer != fp_manufacturer:
        return False

    if fp_model and dev_model != fp_model:
        return False

    return True

def match_device_profile(device: dict[str, Any]) -> tuple[str | None, dict[str, Any] | None]:
    """Match a normalized discovered device to an EyZEE profile."""
    profiles = get_profiles()

    for profile_id, profile in profiles.items():
        fingerprints = profile.get("fingerprints", [])
        if not isinstance(fingerprints, list):
            continue

        for fingerprint in fingerprints:
            if not isinstance(fingerprint, dict):
                continue
            if _matches_fingerprint(device, fingerprint):
                return profile_id, deepcopy(profile)

    return None, None


def enrich_discovered_device(device: dict[str, Any]) -> dict[str, Any]:
    """Add EyZEE profile information to a discovered device."""
    enriched = deepcopy(device)

    profile_id, profile = match_device_profile(device)
    if not profile_id or not profile:
        enriched["profile_id"] = None
        enriched["profile_match"] = False
        return enriched

    display = profile.get("display", {})
    classification = profile.get("classification", {})
    features = profile.get("features", {})
    capabilities = profile.get("capabilities", {})
    entity_map = profile.get("entity_map", {})

    integration = _safe_lower(device.get("integration"))
    integration_entity_map = entity_map.get(integration, {})

    enriched["profile_id"] = profile_id
    enriched["profile_match"] = True
    enriched["profile"] = profile

    enriched["eyzee"] = {
        "brand": display.get("brand"),
        "product_name": display.get("product_name"),
        "short_name": display.get("short_name"),
        "icon": display.get("icon"),
        "device_type": classification.get("device_type"),
        "category": classification.get("category"),
        "metered": classification.get("metered", False),
        "features": features,
        "capabilities": capabilities,
        "entity_map": integration_entity_map,
    }

    return enriched